// Create text/HTML/JSON files locally in the workspace.
const fs=require('fs'),path=require('path');
function safeName(name){return path.basename(name).replace(/[^a-zA-Z0-9._-]/g,'_')}
function createFile(root,name,content){const p=path.join(root,safeName(name));fs.writeFileSync(p,content,'utf8');return p}
function htmlDocument(title,body){return `<!doctype html><html lang="de"><head><meta charset="utf-8"><title>${title}</title></head><body>${body}</body></html>`}
module.exports={createFile,htmlDocument,safeName};
