// Cost-aware device routing. Default: Seeker. PC is opt-in for heavy work only.
const profiles={
  seeker:{name:'Seeker',kind:'local',maxPayloadMb:25,preferred:['telegram','android','wallet','api','light-script','scheduler']},
  pc:{name:'PC',kind:'bridge',host:'192.168.178.67',tailscale:'100.92.87.39',preferred:['docker','compile','large-pdf','large-file','cpu-heavy','persistent-service']},
  runpod:{name:'RunPod',kind:'cloud',preferred:['gpu','large-model','cuda','training']}
};
function choose(task={},opts={}){
  if(opts.device && profiles[opts.device]) return profiles[opts.device];
  const t=String(task.type||task).toLowerCase();
  if(/gpu|cuda|training|large.?model/.test(t))return profiles.runpod;
  if(/docker|compile|large.?pdf|large.?file|cpu.?heavy|persistent/.test(t))return profiles.pc;
  return profiles.seeker;
}
function explain(task,opts={}){const p=choose(task,opts);return {device:p.name,reason:p===profiles.seeker?'lowest latency, no network hop, lowest operational cost':p===profiles.pc?'LAN bridge is better for sustained CPU/storage work':'GPU workload belongs on RunPod'};}
module.exports={profiles,choose,explain};
