import fs from 'node:fs'
import path from 'node:path'

const root=process.cwd(),dist=path.join(root,'dist')
fs.rmSync(dist,{recursive:true,force:true})
fs.mkdirSync(dist,{recursive:true})

// Public static deployment intentionally contains UI/runtime assets only.
// Research reports, docs and strategy/config evidence stay in the repository and
// are served by the governed API, never copied into a public Pages bundle.
for(const name of ['src','public']){
  const from=path.join(root,name)
  if(fs.existsSync(from))fs.cpSync(from,path.join(dist,name),{recursive:true})
}
for(const name of ['index.html','v5.html','strategy-lab.html']){
  const from=path.join(root,name)
  if(fs.existsSync(from))fs.copyFileSync(from,path.join(dist,name))
}

const required=[
  'dist/index.html',
  'dist/v5.html',
  'dist/strategy-lab.html',
  'dist/public/vendor/klinecharts-10.0.2.min.js',
  'dist/public/vendor/pixi-8.19.0.min.js',
  'dist/src/v2/registry.js',
  'dist/src/v2/store.js',
  'dist/src/v4/chart.js',
  'dist/src/v5/app.js',
  'dist/src/v5/v5.css',
  'dist/src/v5/strategy-lab.js',
  'dist/src/v5/strategy-lab-i18n.js',
  'dist/src/v5/strategy-lab-i18n-extra.js',
  'dist/src/v5/strategy-lab-evidence.js',
  'dist/src/v5/portfolio-controls.js',
  'dist/src/v5/trade-review-overlay.js',
  'dist/src/v5/strategy-health.js',
  'dist/src/v5/production-deployments.js',
  'dist/src/v5/strategy-lab.css',
]
for(const file of required)if(!fs.existsSync(path.join(root,file)))throw new Error(`missing build artifact: ${file}`)
for(const forbidden of ['dist/reports','dist/docs','dist/config'])if(fs.existsSync(path.join(root,forbidden)))throw new Error(`research asset leaked into public build: ${forbidden}`)
console.log(`Fabio Decision Gym / Strategy Lab public static build complete: ${dist}`)
