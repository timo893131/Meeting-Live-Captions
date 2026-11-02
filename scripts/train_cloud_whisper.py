"""GPU-only Colab LoRA smoke/pilot. No corpus download, auto deployment or test-set tuning."""
import argparse
import hashlib
import json
import importlib.metadata
import platform
import subprocess
import time
import unicodedata
import wave
from datetime import datetime, timezone
from pathlib import Path
from cloud_training_data import inspect_manifests, digest


def config_hash(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()


def normalize_metric(text):
    # Versioned cloud metric; compare before/after with this same implementation.
    return ''.join(c for c in unicodedata.normalize('NFC',text) if not c.isspace() and c!='\ufeff' and not unicodedata.category(c).startswith('P'))


def dump_new(path, data):
    with Path(path).open('x') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(config, run_dir, resume=False):
    audit, rows = inspect_manifests(config)
    if audit['status'] != 'passed':
        raise ValueError('Data gate failed; run cloud_training_data.py for row-level reasons')
    if config['training']['mode']=='smoke' and (len(rows['train'])>32 or len(rows['validation'])>16):
        raise ValueError('Smoke requires at most 32 train and 16 validation rows in explicitly reviewed manifests')
    # Imports intentionally remain after the data gate; no GPU packages needed for local audit.
    import numpy as np
    import torch
    import transformers
    import peft
    import accelerate
    import jiwer
    from huggingface_hub import HfApi
    from transformers import WhisperProcessor, WhisperForConditionalGeneration, Seq2SeqTrainer, Seq2SeqTrainingArguments, TrainerCallback, set_seed
    from transformers.trainer_utils import get_last_checkpoint
    from peft import LoraConfig, get_peft_model
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU required; select a GPU runtime in Colab')
    if config['training']['mode'] not in ['smoke','pilot']:
        raise ValueError('Expected smoke or pilot mode')
    run_dir=Path(run_dir)
    runtime_packages=dict(torch=torch.__version__,transformers=transformers.__version__,peft=peft.__version__,accelerate=accelerate.__version__,jiwer=importlib.metadata.version('jiwer'),huggingface_hub=importlib.metadata.version('huggingface-hub'))
    lock_file=run_dir/'run-lock.json'
    if resume:
        lock=json.loads(lock_file.read_text())
        if (run_dir/'final-report.json').exists():
            raise ValueError('Completed run is immutable; create a new run directory')
        if lock['config_sha256']!=config_hash(config) or lock['manifest_sha256']!=audit['manifest_sha256']:
            raise ValueError('Resume configuration or dataset hashes differ')
        if lock['runtime_packages']!=runtime_packages:
            raise ValueError('Runtime package versions changed; restore the locked versions before resume')
        revision=lock['base_revision']
    else:
        if run_dir.exists():
            raise FileExistsError('New run directory must not exist')
        info=HfApi().model_info(config['model']['id'], revision=config['model']['revision'] or 'main')
        card=info.card_data.to_dict() if info.card_data is not None else {}
        if card.get('license') not in ['mit','apache-2.0']:
            raise ValueError('Base model license requires review before training')
        revision=info.sha
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir()
        try:
            commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=Path(__file__).parents[1]).strip()
        except Exception:
            commit='unknown'
        lock=dict(config_sha256=config_hash(config),config=config,manifest_sha256=audit['manifest_sha256'],base_model=config['model']['id'],base_revision=revision,base_license=card['license'],runtime_packages=runtime_packages,code_commit=commit,code_sha256={name:digest(Path(__file__).with_name(name)) for name in ['train_cloud_whisper.py','cloud_training_data.py']})
        dump_new(lock_file,lock)
    for name,expected in lock['code_sha256'].items():
        if digest(Path(__file__).with_name(name))!=expected:
            raise ValueError('Training code changed; resume refused')
    checkpoint=get_last_checkpoint(str(run_dir/'checkpoints')) if resume else None
    if resume and not checkpoint:raise ValueError('No checkpoint to resume')
    processor=WhisperProcessor.from_pretrained(config['model']['id'],revision=revision,language='Chinese',task='transcribe',trust_remote_code=False)
    model=WhisperForConditionalGeneration.from_pretrained(config['model']['id'],revision=revision,torch_dtype=torch.float32,use_safetensors=True,trust_remote_code=False)
    if model.config.num_mel_bins!=80:
        raise ValueError('This small-model recipe expects 80 mel bins')
    model.generation_config.language='zh'
    model.generation_config.task='transcribe'
    model.generation_config.forced_decoder_ids=None
    model.config.forced_decoder_ids=None
    set_seed(config['training']['seed'])

    class AudioDataset(torch.utils.data.Dataset):
        def __init__(self, records):self.records=records
        def __len__(self):return len(self.records)
        def __getitem__(self,index):
            row=self.records[index]
            with wave.open(row['_resolved_audio'],'rb') as stream:
                samples=np.frombuffer(stream.readframes(stream.getnframes()),dtype='<i2').astype(np.float32)/32768
            features=processor.feature_extractor(samples,sampling_rate=16000).input_features[0]
            labels=processor.tokenizer(row['text']).input_ids
            if len(labels)>model.config.max_target_positions:
                raise ValueError('Reference exceeds model token limit; segment and review first')
            return dict(input_features=features,labels=labels)

    def collate(batch):
        features=processor.feature_extractor.pad([dict(input_features=r['input_features']) for r in batch],return_tensors='pt')
        labels=processor.tokenizer.pad([dict(input_ids=r['labels']) for r in batch],return_tensors='pt')
        target=labels['input_ids'].masked_fill(labels['attention_mask'].ne(1),-100)
        if (target[:,0]==model.config.decoder_start_token_id).all():target=target[:,1:]
        features['labels']=target
        return features

    def metrics(result):
        prediction=result.predictions[0] if isinstance(result.predictions,tuple) else result.predictions
        prediction=np.where(prediction<0,processor.tokenizer.pad_token_id,prediction)
        labels=np.where(result.label_ids==-100,processor.tokenizer.pad_token_id,result.label_ids)
        hypotheses=[normalize_metric(s) for s in processor.tokenizer.batch_decode(prediction,skip_special_tokens=True)]
        references=[normalize_metric(s) for s in processor.tokenizer.batch_decode(labels,skip_special_tokens=True)]
        if not sum(map(len,references)):raise ValueError('Zero reference characters; CER is undefined')
        return dict(cer=jiwer.cer(references,hypotheses))

    class TimeBudget(TrainerCallback):
        def on_train_begin(self,args,state,control,**kwargs):self.started=time.monotonic()
        def on_step_end(self,args,state,control,**kwargs):
            if time.monotonic()-self.started>=config['training']['max_runtime_minutes']*60:
                control.should_training_stop=True
                control.should_save=True
            return control

    mode=config['training']['mode']
    if mode=='smoke' and (len(rows['train'])>32 or len(rows['validation'])>16):
        raise ValueError('Smoke uses an explicitly chosen manifest with at most 32 train and 16 validation rows; no automatic truncation')
    steps=config['training']['smoke_steps' if mode=='smoke' else 'pilot_steps']
    args=Seq2SeqTrainingArguments(output_dir=str(run_dir/'checkpoints'),max_steps=steps,per_device_train_batch_size=config['training']['batch_size'],per_device_eval_batch_size=1,gradient_accumulation_steps=config['training']['gradient_accumulation_steps'],learning_rate=config['training']['learning_rate'],fp16=config['training']['fp16'],eval_strategy='steps',eval_steps=config['training']['eval_steps'],save_steps=config['training']['save_steps'],save_total_limit=3,load_best_model_at_end=True,metric_for_best_model='cer',greater_is_better=False,logging_steps=1,predict_with_generate=True,generation_max_length=model.config.max_target_positions,remove_unused_columns=False,label_names=['labels'],report_to=[],seed=config['training']['seed'],dataloader_num_workers=0,save_safetensors=True)
    train_data=AudioDataset(rows['train']);validation_data=AudioDataset(rows['validation'])
    baseline_file=run_dir/'baseline-validation.json'
    if not baseline_file.exists():
        baseline_trainer=Seq2SeqTrainer(model=model,args=args,data_collator=collate,eval_dataset=validation_data,compute_metrics=metrics,processing_class=processor.feature_extractor)
        baseline=baseline_trainer.evaluate()
        dump_new(baseline_file,baseline)
        del baseline_trainer
    else:baseline=json.loads(baseline_file.read_text())
    lora=config['lora']
    # Generic PeftModel avoids adding text-model input_ids to Whisper's input_features API.
    model=get_peft_model(model,LoraConfig(r=lora['r'],lora_alpha=lora['alpha'],lora_dropout=lora['dropout'],target_modules=lora['target_modules'],bias='none',revision=revision))
    for parameter in model.parameters():
        if parameter.requires_grad:parameter.data=parameter.data.float()
    trainer=Seq2SeqTrainer(model=model,args=args,train_dataset=train_data,eval_dataset=validation_data,data_collator=collate,compute_metrics=metrics,processing_class=processor.feature_extractor,callbacks=[TimeBudget()])
    started=time.monotonic();torch.cuda.reset_peak_memory_stats()
    trainer.train(resume_from_checkpoint=checkpoint)
    after=trainer.evaluate()
    completed=trainer.state.global_step>=steps
    attempt=run_dir/'attempts'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    attempt.mkdir(parents=True)
    model.save_pretrained(attempt/'adapter',safe_serialization=True)
    processor.save_pretrained(attempt/'processor')
    result=dict(status='completed' if completed else 'stopped_at_step_time_budget',mode=mode,steps=trainer.state.global_step,elapsed_seconds=time.monotonic()-started,baseline_validation=baseline,candidate_validation=after,metric_normalizer='cloud-nfc-punctuation-space-v1',manifest_sha256=audit['manifest_sha256'],base_revision=revision,gpu=torch.cuda.get_device_name(0),peak_gpu_allocated_bytes=torch.cuda.max_memory_allocated(),runtime=dict(python=platform.python_version(),cuda=torch.version.cuda,**runtime_packages),training_completed=completed,test_evaluation='unrun_test_labels_not_used_for_model_selection',realtime_evaluation='unrun',automatic_deployment=False,selected_checkpoint=trainer.state.best_model_checkpoint,adapter_path=str(attempt/'adapter'),processor_path=str(attempt/'processor'))
    dump_new(attempt/'report.json',result)
    if completed:dump_new(run_dir/'final-report.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='training/cloud-whisper-lora.json')
    parser.add_argument('--run-dir',required=True)
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args()
    config=json.loads(Path(args.config).read_text())
    run(config,args.run_dir,args.resume)


if __name__=='__main__':main()
