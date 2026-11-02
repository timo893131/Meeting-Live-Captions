import array
import hashlib
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
import urllib.error
import wave
from pathlib import Path

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import tw_speech_pilot as pilot
from tw_parquet_source import RangeFile


class Response(io.BytesIO):
    def __init__(self,body,status=200,extra=None):
        super().__init__(body);self.status=status;self.headers={'Content-Length':str(len(body)),**(extra or {})}


def config():
    cfg=json.loads((ROOT/'sources/taiwan-mandarin-pilot.json').read_text())
    cfg['source']['download_enabled']=True
    cfg['limits']['interval_seconds']=0
    return cfg


class RangeTests(unittest.TestCase):
    def test_range_seek_cache_and_complete_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            fetcher=pilot.BoundedFetcher(folder,config());data=b'0123456789abcdef'
            class Opener:
                def open(self,req,**kwargs):
                    if req.full_url.endswith('robots.txt'):return Response(b'User-agent: *\nAllow: /\n')
                    a,b=map(int,req.get_header('Range').removeprefix('bytes=').split('-'))
                    return Response(data[a:b+1],206,{'Content-Range':f'bytes {a}-{b}/{len(data)}'})
            fetcher.opener=Opener()
            file=RangeFile(fetcher,'https://huggingface.co/file',len(data),4,hashlib.sha256(data).hexdigest())
            file.seek(-3,2);self.assertEqual(file.read(),b'def');self.assertIsNone(file.verify_complete_hash_if_available())
            file.seek(0);self.assertEqual(file.read(),data);self.assertTrue(file.verify_complete_hash_if_available())
            before=fetcher.state['requests'];file.seek(0);self.assertEqual(file.read(),data);self.assertEqual(fetcher.state['requests'],before)
            self.assertEqual(fetcher.state['body_bytes'],len(data)+len(b'User-agent: *\nAllow: /\n'))
            file.expected_sha256='f'*64
            with self.assertRaisesRegex(ValueError,'hash mismatch'):file.verify_complete_hash_if_available()

    def test_full_download_or_wrong_range_response_is_refused(self):
        for status,header in [(200,{}),(206,{'Content-Range':'bytes 1-3/16'})]:
            with tempfile.TemporaryDirectory() as folder:
                fetcher=pilot.BoundedFetcher(folder,config())
                class Opener:
                    def open(self,req,**kwargs):return Response(b'0123',status,header)
                fetcher.opener=Opener()
                with self.assertRaisesRegex(RuntimeError,'exact byte range'):
                    fetcher.get('https://huggingface.co/file',robots=False,byte_range=(0,3),total_size=16)
                self.assertEqual(fetcher.state['body_bytes'],0)

    def test_redirect_preserves_range_and_failed_endpoint_omits_query(self):
        with tempfile.TemporaryDirectory() as folder:
            fetcher=pilot.BoundedFetcher(folder,config());seen=[]
            class Opener:
                def open(self,req,**kwargs):
                    if req.full_url.endswith('robots.txt'):return Response(b'User-agent: *\nAllow: /\n')
                    seen.append(req.get_header('Range'))
                    if 'huggingface.co/file' in req.full_url:
                        raise urllib.error.HTTPError(req.full_url,302,'redirect',{'Location':'https://us.aws.cdn.hf.co/object?temporary=private'},None)
                    return Response(b'abcd',206,{'Content-Range':'bytes 0-3/4'})
            fetcher.opener=Opener();self.assertEqual(fetcher.get('https://huggingface.co/file',byte_range=(0,3),total_size=4),b'abcd');self.assertEqual(seen,['bytes=0-3','bytes=0-3'])
        with tempfile.TemporaryDirectory() as folder:
            cfg=config();cfg['limits']['max_retries']=0;fetcher=pilot.BoundedFetcher(folder,cfg)
            class Failure:
                def open(self,req,**kwargs):raise urllib.error.HTTPError(req.full_url,500,'failed',{},None)
            fetcher.opener=Failure()
            with self.assertRaises(urllib.error.HTTPError) as caught:fetcher.get('https://huggingface.co/export?private=do-not-log',robots=False)
            self.assertEqual(caught.exception.pilot_request,dict(status=500,host='huggingface.co',path='/export'))


class ParquetTests(unittest.TestCase):
    def test_official_export_fixture_retains_only_fifteen_original_audio_records(self):
        self.assert_export_fixture('cmn_hant_tw/validation/0000.parquet')

    def test_flat_layout_reuses_legacy_snapshot_without_changing_reference_hash(self):
        self.assert_export_fixture('cmn_hant_tw/validation-00000-of-00001.parquet',legacy=True)

    def assert_export_fixture(self,path,legacy=False):
        import pyarrow as pa
        import pyarrow.parquet as pq
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ['raw','processed','review','reports','text_only','manifests']:(root/name).mkdir()
            cfg=config();cfg['limits']['parquet_block_bytes']=65536
            rows=[]
            for index in range(16):
                buffer=io.BytesIO()
                pcm=array.array('h',(int(1200*math.sin(2*math.pi*(200+index*10)*i/16000)) for i in range(81600)))
                with wave.open(buffer,'wb') as stream:
                    stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(16000);stream.writeframes(pcm.tobytes())
                rows.append(dict(audio=dict(bytes=buffer.getvalue(),path=f'synthetic-{index}.wav'),raw_transcription=f'SYNTHETIC CONTRACT TEST {index}',id=index))
            table=pa.Table.from_pylist(rows);temp=root/'fixture.parquet';pq.write_table(table,temp,compression='NONE',row_group_size=16);data=temp.read_bytes()
            card=b'---\nlicense:\n- cc-by-4.0\n---\nSynthetic test card only'
            sha='a'*40
            legacy_bytes=None
            if legacy:
                legacy_bytes=json.dumps(dict(repository='google/fleurs',revision=sha,directory='cmn_hant_tw/validation',file_path=path,file_size=len(data),publisher_sha256=hashlib.sha256(data).hexdigest(),info_sha256='old-info',listing_sha256='old-listing')).encode()
                (root/'raw/parquet-snapshot.json').write_bytes(legacy_bytes)
            class Opener:
                def open(self,req,**kwargs):
                    url=req.full_url
                    if url.endswith('robots.txt'):return Response(b'User-agent: *\nAllow: /\n')
                    if url==cfg['source']['card_url']:return Response(card)
                    if url.endswith('?blobs=true'):return Response(json.dumps(dict(sha=sha,siblings=[dict(rfilename=path,size=len(data),lfs=dict(sha256=hashlib.sha256(data).hexdigest()))])).encode())
                    if '/revision/' in url:return Response(json.dumps(dict(sha=sha)).encode())
                    if '/tree/' in url:raise AssertionError('Nested tree endpoint must not be called')
                    if '/resolve/' in url:
                        a,b=map(int,req.get_header('Range').removeprefix('bytes=').split('-'))
                        return Response(data[a:b+1],206,{'Content-Range':f'bytes {a}-{b}/{len(data)}'})
                    raise AssertionError('Viewer rows API must not be called')
            fetcher=pilot.BoundedFetcher(root,cfg);fetcher.opener=Opener();progress={}
            records,failures=pilot.collect(root,cfg,fetcher,progress)
            self.assertEqual(len(records),15);self.assertEqual(failures,[])
            self.assertEqual(progress['parquet_rows_loaded_in_blocks'],16);self.assertEqual(progress['parquet_rows_materialized'],15)
            self.assertIsNone(progress['downloaded_hours'])
            if legacy:
                self.assertEqual((root/'raw/parquet-snapshot.json').read_bytes(),legacy_bytes)
                self.assertTrue(all(row['provider_rows_sha256']==hashlib.sha256(legacy_bytes).hexdigest() for row in records))
            for i,row in enumerate(records):
                self.assertEqual((root/row['audio_filepath']).read_bytes(),rows[i]['audio']['bytes'])
                self.assertFalse(row['training_ready']);self.assertFalse(row['local_reference_verified']);self.assertIsNone(row['speaker_id']);self.assertEqual(row['split'],'unassigned')
            before=fetcher.state['requests'];again,_=pilot.collect(root,cfg,fetcher,{})
            self.assertEqual(again,records);self.assertEqual(before,fetcher.state['requests'])


@unittest.skipUnless(importlib.util.find_spec('pyarrow'), 'pyarrow required')
class DiscoveryTests(unittest.TestCase):
    def test_missing_selected_split_reports_actual_paths_without_audio_requests(self):
        from tw_parquet_source import collect_parquet
        from types import SimpleNamespace
        for path in ['cmn_hans_cn/validation/0000.parquet','cmn_hant_tw/train/0000.parquet']:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'raw').mkdir();calls=[];progress={};sha='b'*40
                def get(url,**kwargs):
                    calls.append(url)
                    if url.endswith('?blobs=true'):
                        return json.dumps(dict(sha=sha,siblings=[dict(rfilename=path,size=10)])).encode()
                    if '/revision/' in url:return json.dumps(dict(sha=sha)).encode()
                    raise AssertionError('No audio or tree request allowed')
                with self.assertRaisesRegex(ValueError,'no Parquet export'):
                    collect_parquet(root,config(),SimpleNamespace(get=get),progress)
                self.assertEqual(progress['parquet_discovery']['matching_file_count'],0)
                self.assertEqual(progress['parquet_discovery']['path_preview'],[path])
                self.assertEqual(len(calls),2)
                self.assertTrue((root/'raw/parquet-files-metadata.json').exists())

    def test_metadata_revision_mismatch_rejected(self):
        from tw_parquet_source import collect_parquet
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            def get(url,**kwargs):
                return json.dumps(dict(sha=('c' if url.endswith('?blobs=true') else 'b')*40,siblings=[])).encode()
            with self.assertRaisesRegex(ValueError,'does not match immutable revision'):
                collect_parquet(Path(folder),config(),SimpleNamespace(get=get),{})


if __name__=='__main__':unittest.main()
