import fs from 'node:fs'
import path from 'node:path'
const root=process.cwd(),dist=path.join(root,'dist')
fs.rmSync(dist,{recursive:true,force:true});fs.mkdirSync(dist,{recursive:true})
for(const name of ['src','public','reports','docs','config']){const from=path.join(root,name);if(fs.existsSync(from))fs.cpSync(from,path.join(dist,name),{recursive:true})}
for(const name of ['index.html','v5.html','README.md']){const from=path.join(root,name);if(fs.existsSync(from))fs.copyFileSync(from,path.join(dist,name))}
const required=['dist/index.html','dist/v5.html','dist/public/vendor/klinecharts-10.0.2.min.js','dist/public/vendor/pixi-8.19.0.min.js','dist/src/v2/registry.js','dist/src/v2/store.js','dist/src/v4/chart.js','dist/src/v5/app.js','dist/src/v5/v5.css','dist/config/research/node_registry.yaml','dist/config/strategies/MR_BROAD_V3.json']
for(const file of required)if(!fs.existsSync(path.join(root,file)))throw new Error(`missing build artifact: ${file}`)
console.log(`Fabio Decision Gym V5 static build complete: ${dist}`)
