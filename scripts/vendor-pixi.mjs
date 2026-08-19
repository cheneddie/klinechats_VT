import fs from 'node:fs'
import path from 'node:path'

const root=process.cwd()
const version='8.19.0'
const source=path.join(root,'node_modules','pixi.js','dist','pixi.min.js')
const target=path.join(root,'public','vendor',`pixi-${version}.min.js`)
if(!fs.existsSync(source))throw new Error(`PixiJS ${version} not installed: ${source}`)
fs.mkdirSync(path.dirname(target),{recursive:true})
fs.copyFileSync(source,target)
console.log(`Vendored PixiJS ${version}: ${target}`)
