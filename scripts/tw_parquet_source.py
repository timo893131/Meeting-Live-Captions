"""Read a bounded pilot from the same official HF dataset's Parquet export, not Viewer rows."""
import hashlib
import io
import json
import re
import urllib.parse
from pathlib import PurePosixPath


def stable_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)+'\n').encode()


def preserve(path, data):
    if path.exists():
        if path.read_bytes()!=data:
            raise ValueError('Existing immutable source differs; choose a new dataset root')
    else:
        with path.open('xb') as stream:stream.write(data)


class RangeFile(io.RawIOBase):
    def __init__(self, fetcher, url, size, block_size, expected_sha256=None):
        super().__init__()
        if type(size) is not int or size<=0 or type(block_size) is not int or block_size<=0:
            raise ValueError('Invalid Parquet file size or block size')
        self.fetcher=fetcher;self.url=url;self.size=size;self.block_size=block_size
        self.position=0;self.blocks={};self.expected_sha256=expected_sha256

    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.position
    def seek(self,offset,whence=0):
        target=offset if whence==0 else self.position+offset if whence==1 else self.size+offset if whence==2 else -1
        if not 0<=target<=self.size:raise ValueError('Parquet seek outside declared file')
        self.position=target;return target

    def read(self,n=-1):
        if self.closed:raise ValueError('Read of closed Parquet source')
        remaining=min(self.size-self.position,n) if n is not None and n>=0 else self.size-self.position
        parts=[]
        while remaining:
            start=self.position//self.block_size*self.block_size
            if start not in self.blocks:
                end=min(self.size,start+self.block_size)-1
                self.blocks[start]=self.fetcher.get(self.url,byte_range=(start,end),total_size=self.size,max_bytes=self.block_size)
            block=self.blocks[start];offset=self.position-start
            amount=min(remaining,len(block)-offset)
            if amount<=0:raise ValueError('Invalid cached range length')
            parts.append(block[offset:offset+amount]);self.position+=amount;remaining-=amount
        return b''.join(parts)

    def readinto(self,buffer):
        data=self.read(len(buffer));buffer[:len(data)]=data;return len(data)

    def verify_complete_hash_if_available(self):
        offsets=range(0,self.size,self.block_size)
        if not self.expected_sha256 or any(start not in self.blocks for start in offsets):return None
        h=hashlib.sha256()
        for start in range(0,self.size,self.block_size):h.update(self.blocks[start])
        if h.hexdigest()!=self.expected_sha256:raise ValueError('Full Parquet source hash mismatch')
        return True


def collect_parquet(root,config,fetcher,progress=None):
    import pyarrow.parquet as pq
    source=config['source'];limits=config['limits']
    repo=source['repository_id']
    if repo!='google/fleurs':raise ValueError('Unexpected Parquet repository')
    directory=source['parquet_directory']
    if directory!='cmn_hant_tw/validation':raise ValueError('Unexpected Parquet configuration/split')
    revision=urllib.parse.quote(source['parquet_revision'],safe='')
    info_url=f'https://huggingface.co/api/datasets/{repo}/revision/{revision}'
    info_bytes=fetcher.get(info_url,max_bytes=4194304);info=json.loads(info_bytes)
    commit=info.get('sha')
    if not isinstance(commit,str) or not re.fullmatch('[0-9a-f]{40}',commit):raise ValueError('Missing immutable dataset export revision')
    tree_url=f'https://huggingface.co/api/datasets/{repo}/tree/{commit}/{urllib.parse.quote(directory,safe="")}?recursive=false&expand=false'
    tree_bytes=fetcher.get(tree_url,max_bytes=4194304);tree=json.loads(tree_bytes)
    if not isinstance(tree,list) or len(tree)>1000:raise ValueError('Invalid bounded Parquet directory listing')
    files=[]
    for item in tree:
        if not isinstance(item,dict) or not isinstance(item.get('path'),str):raise ValueError('Invalid Parquet directory entry')
        file=item['path']
        if item.get('type')=='file' and file.startswith(directory+'/') and file.endswith('.parquet'):
            parts=PurePosixPath(file).parts
            if '..' in parts or file.startswith('/') or type(item.get('size')) is not int or item['size']<=0:raise ValueError('Invalid Parquet path/size')
            files.append(item)
    if not files:raise ValueError('Official dataset has no Parquet export for selected configuration/split')
    files.sort(key=lambda f:f['path'])
    if limits.get('max_parquet_shards')!=1:raise ValueError('Pilot requires exactly one Parquet shard maximum')
    file=files[0]
    url=f'https://huggingface.co/datasets/{repo}/resolve/{commit}/{urllib.parse.quote(file["path"],safe="/")}'
    lfs=file.get('lfs') or {};full_sha=lfs.get('oid') or lfs.get('sha256')
    if full_sha is not None and not re.fullmatch('[a-f0-9]{64}',full_sha):raise ValueError('Invalid source LFS hash')
    snapshot=dict(repository=repo,revision=commit,directory=directory,file_path=file['path'],file_size=file['size'],publisher_sha256=full_sha,info_sha256=hashlib.sha256(info_bytes).hexdigest(),listing_sha256=hashlib.sha256(tree_bytes).hexdigest())
    snapshot_bytes=stable_json(snapshot)
    preserve(root/'raw/parquet-snapshot.json',snapshot_bytes)
    if progress is not None:progress.update(transport='hub_parquet',parquet_snapshot=snapshot,downloaded_hours=None,transfer_scope='Range blocks may contain unselected audio; selected_audio_hours is measured separately')
    media=RangeFile(fetcher,url,file['size'],limits['parquet_block_bytes'],full_sha)
    provider=pq.ParquetFile(media)
    columns=[name for name in ['audio','raw_transcription','transcription','path','id','speaker_id','num_samples','sampling_rate'] if name in provider.schema_arrow.names]
    if 'audio' not in columns or not any(name in columns for name in ['raw_transcription','transcription']):raise ValueError('Parquet export lacks paired audio/text columns')
    selected=[];row_offset=0;fetched_rows=0
    for index in range(provider.num_row_groups):
        group=provider.metadata.row_group(index)
        if group.total_byte_size>limits['max_parquet_group_uncompressed_bytes']:
            raise ValueError('Parquet row group exceeds decoded-memory budget')
        table=provider.read_row_group(index,columns=columns,use_threads=False)
        fetched_rows+=table.num_rows
        take=min(limits['samples']-len(selected),table.num_rows)
        selected.extend((row_offset+i,row) for i,row in enumerate(table.slice(0,take).to_pylist()))
        row_offset+=table.num_rows
        if len(selected)>=limits['samples']:break
    verified_full=media.verify_complete_hash_if_available()
    # Actual original audio bytes are kept, never a decoded/re-encoded substitute.
    records=[];failures=[]
    cache_times=[entry['fetched_at'] for entry in fetcher.state['cache'].values() if entry.get('url')==url and 'byte_range' in entry]
    if not cache_times:raise ValueError('No verified source ranges recorded')
    fetched_at=min(cache_times)
    card=(root/'raw/dataset-card.md').read_bytes();card_hash=hashlib.sha256(card).hexdigest()
    for row_index,row in selected:
        sample_id=f'fleurs-cmn-hant-tw-validation-{row_index}'
        try:
            audio=row.get('audio');text=row.get('raw_transcription') or row.get('transcription')
            if not isinstance(audio,dict) or not isinstance(audio.get('bytes'),bytes) or not audio['bytes']:raise ValueError('No embedded original audio bytes')
            if not isinstance(text,str) or not text.strip():raise ValueError('No provider reference text')
            payload=audio['bytes']
            if len(payload)>limits['max_file_bytes']:raise ValueError('Selected audio exceeds per-file budget')
            audio_path=root/'raw'/f'{sample_id}.audio';preserve(audio_path,payload)
            speaker=row.get('speaker_id')
            if speaker is not None and not isinstance(speaker,str):speaker=None
            record=dict(id=sample_id,audio_filepath=str(audio_path.relative_to(root)),text=text,language=source['language'],duration=None,source_url=source['dataset_url'],recording_id=f'fleurs:{row.get("path") or audio.get("path") or row_index}',recording_identity_scope='provider_file_or_row_only_original_session_unknown',speaker_id=speaker,segment_start=0,segment_end=None,transcript_status=source['reference_status'],license_status='approved',license=source['expected_license'],attribution=source['attribution'],license_evidence_sha256=card_hash,provider_rows_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),sha256=hashlib.sha256(payload).hexdigest(),split='unassigned',provider_split='validation',dataset_role='pipeline_development_only',downloaded_at=fetched_at,language_spans=[],language_annotation_status='not_reviewed',local_reference_verified=False,training_ready=False,transport='hub_parquet',parquet_revision=commit,parquet_file=file['path'],parquet_row_index=row_index)
            records.append(record)
        except ValueError as error:
            failures.append(dict(id=sample_id,reason=str(error)))
            if isinstance(row.get('raw_transcription') or row.get('transcription'),str):
                path=root/'text_only'/f'{sample_id}.json'
                preserve(path,stable_json(dict(id=sample_id,text=row.get('raw_transcription') or row.get('transcription'),source_url=source['dataset_url'],parquet_revision=commit,parquet_row_index=row_index,status='text_only_unpaired',training_ready=False)))
    if progress is not None:progress.update(parquet_rows_loaded_in_blocks=fetched_rows,parquet_rows_materialized=len(records),parquet_complete_publisher_hash_verified=verified_full,transfer_scope='Parquet blocks may contain additional unselected rows; downloaded_hours is unknown, selected_audio_hours is measured after decoding')
    preserve(root/'manifests/downloaded.jsonl',''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records).encode())
    return records,failures
