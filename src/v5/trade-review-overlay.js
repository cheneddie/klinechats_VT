(()=>{
  const SVG_NS='http://www.w3.org/2000/svg';
  const apiBase=()=>String(localStorage.getItem('strategyLabApi')||'http://127.0.0.1:8765/api').replace(/\/$/,'');
  const num=v=>{const n=Number(v);return Number.isFinite(n)?n:null};
  const ms=v=>{if(v==null)return null;const n=typeof v==='number'?v:Date.parse(v);return Number.isFinite(n)?n:null};
  const fmt=(v,d=1)=>{const n=num(v);return n==null?'—':n.toFixed(d).replace(/\.0$/,'')};
  let cleanup=()=>{};

  async function getTrade(runId,tradeId){
    const r=await fetch(`${apiBase()}/v5/strategy-lab/backtests/${encodeURIComponent(runId)}/trades/${encodeURIComponent(tradeId)}`,{signal:AbortSignal.timeout(30000)});
    if(!r.ok)throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
    return r.json();
  }

  function svgEl(name,attrs={}){
    const el=document.createElementNS(SVG_NS,name);
    for(const [k,v] of Object.entries(attrs))el.setAttribute(k,String(v));
    return el;
  }

  function addText(svg,text,x,y,color,anchor='start'){
    const t=svgEl('text',{x,y,fill:color,'font-size':12,'font-weight':700,'text-anchor':anchor,'paint-order':'stroke','stroke':'#07101b','stroke-width':4,'stroke-linejoin':'round'});
    t.textContent=text;
    svg.appendChild(t);
  }

  function point(chart,time,price){
    const t=ms(time),p=num(price);
    if(t==null||p==null)return null;
    try{
      const out=chart.convertToPixel({timestamp:t,value:p},{paneId:'candle_pane'});
      return Number.isFinite(out?.x)&&Number.isFinite(out?.y)?{x:Number(out.x),y:Number(out.y)}:null;
    }catch{return null}
  }

  function priceY(chart,price){
    const p=num(price);if(p==null)return null;
    try{const out=chart.convertToPixel({value:p},{paneId:'candle_pane'});return Number.isFinite(out?.y)?Number(out.y):null}catch{return null}
  }

  function buildBanner(host,trade){
    host.querySelector('.trade-review-banner')?.remove();
    const net=num(trade.net_r)||0;
    const win=net>=0;
    const banner=document.createElement('div');
    banner.className='trade-review-banner';
    Object.assign(banner.style,{position:'absolute',left:'10px',top:'10px',zIndex:'11',pointerEvents:'none',padding:'8px 10px',borderRadius:'9px',background:'rgba(6,16,26,.88)',border:`1px solid ${win?'rgba(82,211,167,.65)':'rgba(255,117,137,.65)'}`,boxShadow:'0 6px 18px rgba(0,0,0,.22)',font:'600 12px/1.35 Inter,system-ui,sans-serif',color:'#eef5ff',backdropFilter:'blur(6px)'});
    const direction=String(trade.direction||'').toUpperCase();
    banner.innerHTML=`<div style="color:${win?'#80e6c0':'#ff9bab'};font-weight:800">${direction} · ${net>=0?'+':''}${fmt(net,3)}R · ${String(trade.exit_reason||'EXIT')}</div><div style="margin-top:2px;color:#b7d1ec">ENTRY ${fmt(trade.entry_price,1)} → EXIT ${fmt(trade.exit_price,1)} · ${fmt(trade.holding_seconds,0)}s</div><div style="color:#8da4bf">MFE ${fmt(trade.mfe_r,3)}R · MAE ${fmt(trade.mae_r,3)}R · Capture ${trade.capture_ratio==null?'—':(Number(trade.capture_ratio)*100).toFixed(1)+'%'}</div>`;
    host.appendChild(banner);
  }

  function render(host,trade){
    const current=window.FabioV4?.chart?.current?.();
    const chart=current?.chart;
    if(!host||!chart)return false;
    host.style.position='relative';
    host.querySelector('.trade-review-svg')?.remove();
    buildBanner(host,trade);

    const w=Math.max(1,host.clientWidth),h=Math.max(1,host.clientHeight);
    const svg=svgEl('svg',{class:'trade-review-svg',width:w,height:h,viewBox:`0 0 ${w} ${h}`});
    Object.assign(svg.style,{position:'absolute',inset:'0',zIndex:'10',pointerEvents:'none',overflow:'visible'});
    host.appendChild(svg);

    const entry=point(chart,trade.entry_time,trade.entry_price);
    const exit=point(chart,trade.exit_time,trade.exit_price);
    if(!entry||!exit)return false;
    const left=Math.min(entry.x,exit.x),right=Math.max(entry.x,exit.x),span=Math.max(4,right-left);
    const entryY=entry.y,exitY=exit.y,stopY=priceY(chart,trade.stop_price),targetY=priceY(chart,trade.target_price);
    const net=num(trade.net_r)||0,win=net>=0,direction=String(trade.direction||'').toLowerCase(),long=direction==='long';
    const winColor='#52d3a7',lossColor='#ff7589',entryColor='#72a8ff',targetColor='#52d3a7',stopColor='#ff7589',exitColor=win?winColor:lossColor;

    svg.appendChild(svgEl('rect',{x:left,y:0,width:span,height:h,fill:'#72a8ff','fill-opacity':'.035'}));
    if(stopY!=null){const top=Math.min(entryY,stopY);svg.appendChild(svgEl('rect',{x:left,y:top,width:span,height:Math.max(2,Math.abs(stopY-entryY)),fill:lossColor,'fill-opacity':'.075'}));}
    if(targetY!=null){const top=Math.min(entryY,targetY);svg.appendChild(svgEl('rect',{x:left,y:top,width:span,height:Math.max(2,Math.abs(targetY-entryY)),fill:winColor,'fill-opacity':'.06'}));}

    if(stopY!=null){svg.appendChild(svgEl('line',{x1:left,x2:right+70,y1:stopY,y2:stopY,stroke:stopColor,'stroke-width':1.5,'stroke-dasharray':'7 5','stroke-opacity':'.85'}));addText(svg,`SL ${fmt(trade.stop_price,1)}`,Math.min(w-8,right+74),stopY-5,stopColor,right+74>w-90?'end':'start');}
    if(targetY!=null){svg.appendChild(svgEl('line',{x1:left,x2:right+70,y1:targetY,y2:targetY,stroke:targetColor,'stroke-width':1.5,'stroke-dasharray':'7 5','stroke-opacity':'.85'}));addText(svg,`TP ${fmt(trade.target_price,1)}`,Math.min(w-8,right+74),targetY-5,targetColor,right+74>w-90?'end':'start');}

    svg.appendChild(svgEl('line',{x1:entry.x,y1:entry.y,x2:exit.x,y2:exit.y,stroke:exitColor,'stroke-width':2.2,'stroke-opacity':'.8'}));

    const s=10;
    const entryPts=long?`${entry.x},${entry.y-s} ${entry.x-s},${entry.y+s} ${entry.x+s},${entry.y+s}`:`${entry.x},${entry.y+s} ${entry.x-s},${entry.y-s} ${entry.x+s},${entry.y-s}`;
    svg.appendChild(svgEl('polygon',{points:entryPts,fill:entryColor,stroke:'#dbe9ff','stroke-width':1.6}));
    addText(svg,`ENTRY ${fmt(trade.entry_price,1)}`,entry.x+13,entry.y-12,entryColor);

    const d=9;
    svg.appendChild(svgEl('polygon',{points:`${exit.x},${exit.y-d} ${exit.x+d},${exit.y} ${exit.x},${exit.y+d} ${exit.x-d},${exit.y}`,fill:exitColor,stroke:'#f7fbff','stroke-width':1.6}));
    addText(svg,`EXIT ${fmt(trade.exit_price,1)} · ${net>=0?'+':''}${fmt(net,3)}R`,exit.x+13,exit.y+18,exitColor);

    host.dataset.tradeReviewOverlay='ready';
    host.dataset.tradeReviewId=String(trade.trade_id||'');
    return true;
  }

  async function attach(runId,tradeId){
    const detail=await getTrade(runId,tradeId);
    const trade=detail.trade||{};
    for(let i=0;i<60;i++){
      const host=document.getElementById('tradeChart');
      const current=window.FabioV4?.chart?.current?.();
      if(host&&current?.chart&&String(current?.c?.id||'')===String(trade.event_id||'')){
        cleanup();
        const redraw=()=>requestAnimationFrame(()=>render(host,trade));
        const actions=['onZoom','onScroll','onVisibleRangeChange','onPaneDrag'];
        for(const name of actions){try{current.chart.subscribeAction(name,redraw)}catch{}}
        const ro=new ResizeObserver(redraw);ro.observe(host);
        cleanup=()=>{for(const name of actions){try{current.chart.unsubscribeAction(name,redraw)}catch{}}ro.disconnect();host.querySelector('.trade-review-svg')?.remove();host.querySelector('.trade-review-banner')?.remove();delete host.dataset.tradeReviewOverlay;};
        redraw();
        window.__STRATEGY_LAB_TRADE_OVERLAY__={trade,runId,tradeId,render:()=>render(host,trade)};
        return;
      }
      await new Promise(r=>setTimeout(r,100));
    }
    throw new Error(`Trade Review chart not ready for ${tradeId}`);
  }

  document.addEventListener('click',event=>{
    const row=event.target.closest?.('.trade-item[data-trade]');
    if(!row)return;
    const runId=document.getElementById('reviewBt')?.value||'';
    const tradeId=row.dataset.trade||'';
    if(!runId||!tradeId)return;
    attach(runId,tradeId).catch(err=>console.error('trade-review-overlay',err));
  },true);

  window.StrategyLabTradeOverlay={attach,render,current:()=>window.__STRATEGY_LAB_TRADE_OVERLAY__||null};
})();
