import fs from 'node:fs'
import path from 'node:path'
const root=process.cwd(),dist=path.join(root,'dist')
fs.rmSync(dist,{recursive:true,force:true});fs.mkdirSync(dist,{recursive:true})
for(const name of ['src','public','reports']){
  const from=path.join(root,name);if(fs.existsSync(from))fs.cpSync(from,path.join(dist,name),{recursive:true})
}
for(const name of ['index.html','README.md']){const from=path.join(root,name);if(fs.existsSync(from))fs.copyFileSync(from,path.join(dist,name))}
const required=['dist/index.html','dist/public/vendor/klinecharts-10.0.2.min.js','dist/src/main.js','dist/reports/MTX_2027_DATA_QA.json']
for(const file of required)if(!fs.existsSync(path.join(root,file)))throw new Error(`missing build artifact: ${file}`)
console.log(`Static build complete: ${dist}`)
