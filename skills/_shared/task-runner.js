// Minimal task runner contract. The caller must provide explicit task intent.
const {choose}=require('./device-router');
function plan(task,opts={}){const device=choose(task,opts);return {task,device:device.name,requiresUserApproval:device.name==='PC'&&Boolean(opts.wakePC),steps:[`route:${device.name}`,`execute:${task.type||'task'}`]};}
module.exports={plan};
