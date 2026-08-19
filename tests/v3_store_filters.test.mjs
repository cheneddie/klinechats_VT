import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'

function loadStore(){
  const memory=new Map()
  const context={
    console,
    URLSearchParams,
    AbortSignal,
    crypto:{randomUUID:()=> 'qa-id'},
    localStorage:{
      getItem:key=>memory.get(key)??null,
      setItem:(key,value)=>memory.set(key,String(value))
    },
    FabioV2:{nodes:[{id:'MR_CLEAR_RECLAIM'}]},
  }
  context.window=context
  vm.createContext(context)
  vm.runInContext(fs.readFileSync('src/v2/store.js','utf8'),context,{filename:'src/v2/store.js'})
  return context.FabioV2.store
}

test('offline loadNodeCases preserves YES/NO filters and limit',async()=>{
  const store=loadStore()
  store.state.apiOnline=false
  store.state.cases.push(
    {id:'yes-1',nodes:{MR_CLEAR_RECLAIM:true}},
    {id:'yes-2',nodes:{MR_CLEAR_RECLAIM:true}},
    {id:'no-1',nodes:{MR_CLEAR_RECLAIM:false}},
  )
  const yes=await store.loadNodeCases('MR_CLEAR_RECLAIM',{answer:true,limit:1})
  const no=await store.loadNodeCases('MR_CLEAR_RECLAIM',{answer:false,limit:10})
  assert.deepEqual(yes.map(x=>x.id),['yes-1'])
  assert.deepEqual(no.map(x=>x.id),['no-1'])
})
