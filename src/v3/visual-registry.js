window.FabioV3=window.FabioV3||{};
(()=>{
const V={
CTX_VALUE:{family:'context_band',label:'Previous Value',layer:'context',tone:'context',focus:'range'},
AUC_ATTEMPT:{family:'trigger_marker',label:'Auction Attempt',layer:'auction',tone:'auction',focus:'point'},
AUC_EXTREME:{family:'extreme_marker',label:'Extreme',layer:'auction',tone:'extreme',focus:'point'},
MR_REJECTION:{family:'structure_path',label:'Rejection',layer:'mr',tone:'rejection',focus:'segment'},
MR_CLEAR_RECLAIM:{family:'trigger_marker',label:'Clear Reclaim',layer:'mr',tone:'reclaim',focus:'point'},
MR_RECLAIM_LEG:{family:'structure_path',label:'Reclaim Leg',layer:'mr',tone:'leg',focus:'segment'},
MR_LVN:{family:'context_band',label:'Reclaim-Leg LVN',layer:'location',tone:'lvn',focus:'range'},
MR_PULLBACK:{family:'range_box',label:'First Pullback',layer:'location',tone:'pullback',focus:'range'},
MR_ENTRY:{family:'trade_marker',label:'MR Entry',layer:'trade',tone:'entry',focus:'point'},
BO_ACCEPTANCE:{family:'range_box',label:'Acceptance',layer:'bo',tone:'acceptance',focus:'range'},
BO_DISPLACEMENT:{family:'structure_path',label:'Displacement',layer:'bo',tone:'impulse',focus:'segment'},
BO_IMPULSE_LEG:{family:'structure_path',label:'Impulse Leg',layer:'bo',tone:'leg',focus:'segment'},
BO_LVN:{family:'context_band',label:'Impulse-Leg LVN',layer:'location',tone:'lvn',focus:'range'},
BO_PULLBACK:{family:'range_box',label:'BO Pullback',layer:'location',tone:'pullback',focus:'range'},
BO_RESPONSE:{family:'trigger_marker',label:'Response',layer:'bo',tone:'response',focus:'point'},
BO_ENTRY:{family:'trade_marker',label:'BO Entry',layer:'trade',tone:'entry',focus:'point'},
WAIT_AMBIGUOUS:{family:'decision_badge',label:'WAIT',layer:'decision',tone:'wait',focus:'point'},
NO_TRADE:{family:'decision_badge',label:'NO TRADE',layer:'decision',tone:'invalid',focus:'point'}
};
const palette={
context:{line:0x7892ad,fill:0x47637f,text:0xd9e7f5},
auction:{line:0x56a8ff,fill:0x2f6fae,text:0xdceeff},
extreme:{line:0xff9b55,fill:0xc86931,text:0xffeadb},
rejection:{line:0xff7087,fill:0x8f3549,text:0xffe0e5},
reclaim:{line:0x5dd8ff,fill:0x237c98,text:0xe0f8ff},
leg:{line:0x7dc4ff,fill:0x2e648d,text:0xe6f5ff},
lvn:{line:0xb393ff,fill:0x6246a8,text:0xf0eaff},
pullback:{line:0xf0c75e,fill:0x8b6e22,text:0xfff3c7},
acceptance:{line:0x49d7a5,fill:0x1e765b,text:0xdffcf2},
impulse:{line:0x38c995,fill:0x1d795b,text:0xddfff3},
response:{line:0x57e2bc,fill:0x257e68,text:0xe0fff7},
entry:{line:0x3de6aa,fill:0x16845d,text:0xe0fff3},
wait:{line:0x9aa9bb,fill:0x566170,text:0xf0f4f8},
invalid:{line:0xff6378,fill:0x8c3142,text:0xffe3e8}
};
function spec(id){return V[id]||{family:'decision_badge',label:id,layer:'decision',tone:'wait',focus:'point'}}
function style(id,answer=true){const s=spec(id),p=palette[answer?s.tone:'invalid']||palette.wait;return{...p,alpha:answer?.9:.72,fillAlpha:answer?.13:.08,lineWidth:answer?2:1.5}}
FabioV3.visualRegistry={nodes:V,palette,spec,style};
})();
