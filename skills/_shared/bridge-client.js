// Reusable HTTP bridge client for PC, Poco X7, and Seeker Termux.
// Secrets stay in environment variables; never hardcode them.
const http = require('http');
const https = require('https');
function request(url, method='GET', body=null, headers={}) {
  return new Promise((resolve,reject)=>{
    const u=new URL(url), lib=u.protocol==='https:'?https:http;
    const data=body==null?null:JSON.stringify(body);
    const req=lib.request({hostname:u.hostname,port:u.port||undefined,path:u.pathname+u.search,method,headers:{...(data?{'Content-Type':'application/json','Content-Length':Buffer.byteLength(data)}:{}),...headers},timeout:35000},res=>{let s='';res.on('data',c=>s+=c);res.on('end',()=>{let d=s;try{d=JSON.parse(s)}catch{}resolve({status:res.statusCode,data:d})})});
    req.on('error',reject); req.on('timeout',()=>{req.destroy();reject(new Error('request timeout'))});
    if(data)req.write(data); req.end();
  });
}
async function runBridge(baseUrl, secret, cmd, timeout=30){return request(baseUrl.replace(/\/$/,'')+'/run','POST',{secret,cmd,timeout});}
module.exports={request,runBridge};
