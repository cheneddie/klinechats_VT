(function(){
  let registered=false
  function register(){
    if(registered || !window.klinecharts || typeof klinecharts.registerOverlay!=='function') return
    klinecharts.registerOverlay({
      name:'fabioMarker',totalStep:1,lock:true,zLevel:50,
      createPointFigures:({coordinates,overlay})=>{
        if(!coordinates?.length) return []
        const p=coordinates[0],d=overlay.extendData||{},buy=d.side==='long',color=d.color||(buy?'#26d7a2':'#ff5d74'),up=d.kind==='entry'?(buy?-1:1):(d.kind==='extreme'?-1:1)
        const tipY=p.y+up*20,baseY=p.y+up*7
        return [
          {type:'polygon',attrs:{coordinates:[{x:p.x,y:tipY},{x:p.x-7,y:baseY},{x:p.x+7,y:baseY}]},styles:{style:'fill',color},ignoreEvent:true},
          {type:'text',attrs:{x:p.x,y:p.y-up*12,text:d.label||'',align:'center',baseline:up<0?'bottom':'top'},styles:{color,backgroundColor:'#07111dcc',borderColor:color,borderSize:1,paddingLeft:5,paddingRight:5,paddingTop:3,paddingBottom:3,borderRadius:4,fontSize:10},ignoreEvent:true}
        ]
      }
    })
    klinecharts.registerOverlay({
      name:'fabioLeg',totalStep:2,lock:true,zLevel:30,
      createPointFigures:({coordinates,overlay})=>{
        if(coordinates?.length<2)return[];const d=overlay.extendData||{},color=d.color||'#9b7cff'
        return [
          {type:'line',attrs:{coordinates:[coordinates[0],coordinates[1]]},styles:{color,size:2,style:'solid'},ignoreEvent:true},
          {type:'text',attrs:{x:(coordinates[0].x+coordinates[1].x)/2,y:(coordinates[0].y+coordinates[1].y)/2-10,text:d.label||'Causal Leg',align:'center',baseline:'bottom'},styles:{color,backgroundColor:'#07111dcc',fontSize:10,paddingLeft:4,paddingRight:4,paddingTop:2,paddingBottom:2},ignoreEvent:true}
        ]
      }
    })
    registered=true
  }
  function marker(chart,{time,value,label,side='long',kind='event',color}){
    if(!chart||!time||!Number.isFinite(value))return null
    try{return chart.createOverlay({name:'fabioMarker',lock:true,points:[{timestamp:Date.parse(time),value}],extendData:{label,side,kind,color}})}catch(e){console.warn('marker overlay',e);return null}
  }
  function leg(chart,{time1,value1,time2,value2,label,color}){
    if(!chart||!time1||!time2||![value1,value2].every(Number.isFinite))return null
    try{return chart.createOverlay({name:'fabioLeg',lock:true,points:[{timestamp:Date.parse(time1),value:value1},{timestamp:Date.parse(time2),value:value2}],extendData:{label,color}})}catch(e){console.warn('leg overlay',e);return null}
  }
  window.FabioOverlays={register,marker,leg}
})()
