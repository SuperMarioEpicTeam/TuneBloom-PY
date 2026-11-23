"use strict";
const IC={info:"\ue0f9",list:"\ue2e0",disc:"\ue494",lines:"\ue55a",m3:"\ue34b",m4:"\ue34c",m2:"\ue34a",piano:"\ue561",fmus:"\ue55e",folders:"\ue33f",vol2:"\ue1ab",
 pen:"\ue12f",file:"\ue0c0",folder:"\ue0d7",fopen:"\ue247",save:"\ue14d",saveall:"\ue40f",fout:"\ue0c8",door:"\ue3d6",cpu:"\ue0a9",play:"\ue13c",pause:"\ue12e",
 sq:"\ue167",x:"\ue1b2",plus:"\ue13d",tprops:"\ue4db",set2:"\ue245",bin:"\ue1f2",ext:"\ue0b9",case:"\ue3d9",music:"\ue122",vol:"\ue1a9",dl:"\ue2e0",rst:"\ue452",check:"\u2713"};
const ICON_FOR={stream:IC.disc,wave:IC.lines,seq:IC.m3,bank:IC.piano,warc:IC.fmus,group:IC.folders,player:IC.vol2};
const NAV=[["info","Project Info",IC.info,"info"],["allsounds","All Sounds",IC.list],["stream","Stream Sounds",IC.disc],["wave","Wave Sounds",IC.lines],["seq","Sequence Sounds",IC.m3],"-",
 ["allsets","All Sound Sets",IC.m4],["wavesets","Wave Sound Sets",IC.lines],["seqsets","Sequence Sound Sets",IC.m2],["banks","Banks",IC.piano],["warcs","Wave Archives",IC.fmus],["groups","Groups",IC.folders],["players","Players",IC.vol2],"-",
 ["wavefiles","Wave Files",IC.lines],["seqfiles","Sequence Files",IC.m3],["bankfiles","Bank Files",IC.piano]];
const S={st:{open:false},cat:"info",rows:[],sel:null,props:[],tabs:[],tab:"info",search:"",showSearch:false,rtab:0,editor:null,bank:null,regSel:0,insSel:0,playing:null,seqSel:null,menu:null};
const $=id=>document.getElementById(id);
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const ic=c=>`<i class="i">${c}</i>`;
async function api(path,opt){const r=await fetch("/api/"+path,opt);if(!r.ok){let m=r.statusText;try{m=(await r.json()).error||m}catch(e){}throw new Error(m)}return r}
const jget=async p=>(await api(p)).json();
const jpost=async(p,b)=>(await api(p,{method:"POST",body:JSON.stringify(b)})).json();
function toast(m){const t=document.createElement("div");t.className="toast";t.textContent=m;document.body.appendChild(t);setTimeout(()=>t.remove(),9000)}

/* ---------- menu ---------- */
const MENUS={File:[[IC.file+" New","new"],[IC.fopen+" Open","open"],[IC.fopen+" Add BFGRP…","addgrp",1],[IC.plus+" Add Stream Sound…","addstream",1],[IC.plus+" Add Wave Sound…","addwave",1],[IC.plus+" Add Sequence Sound…","addseq",1],[IC.save+" Save","save",1],[IC.saveall+" Save As","saveas",1],[IC.fout+" Close","close",1],[IC.door+" Exit","exit"]],
 More:[[IC.cpu+" System Window","sys"]],Help:[[IC.info+" About","about"]]};
function drawMenu(){const m=$("menubar");m.innerHTML=Object.keys(MENUS).map(k=>`<div class="mi${S.menu===k?" open":""}" data-m="${k}">${k}</div>`).join("");
 m.querySelectorAll(".mi").forEach(e=>{e.onclick=ev=>{ev.stopPropagation();S.menu=S.menu===e.dataset.m?null:e.dataset.m;drawMenu();if(S.menu){const d=document.createElement("div");d.className="dd";d.style.left=e.offsetLeft+"px";
  d.innerHTML=MENUS[S.menu].map(([l,a,need])=>`<div class="${need&&!S.st.open?"dis":""}" data-a="${a}"><span class="i">${l.slice(0,1)}</span>${esc(l.slice(1))}</div>`).join("");
  d.onclick=ev=>{const t=ev.target.closest("[data-a]");if(!t||t.classList.contains("dis"))return;S.menu=null;drawMenu();act(t.dataset.a)};m.appendChild(d)}}});}
document.addEventListener("click",()=>{if(S.menu){S.menu=null;drawMenu()}});
async function act(a){
 if(a==="open"||a==="new")return openDialog();
 if(a==="addstream")return addStreamFlow();
 if(a==="addwave")return addWaveFlow();
 if(a==="addseq")return addSeqFlow();
 if(a==="addgrp")return pathDialog("Add BFGRP","",async p=>{try{const r=await jpost("addgrp",{path:p});toast(r.files+" fichiers fournis par le BFGRP");S.props=S.sel!==null?await jget(`item?cat=${S.cat}&i=${S.sel}`):[];drawAll()}catch(e){toast(e.message)}});
 if(a==="save"){await jpost("save",{});await refreshState();toast("Saved")}
 if(a==="saveas")return pathDialog("Save As",S.st.path||"",async p=>{await jpost("save",{path:p});await refreshState()});
 if(a==="close"){await jpost("close",{});S.tabs=[];S.tab="info";S.cat="info";await refreshState()}
 if(a==="exit")window.close();
 if(a==="about")return dlg("About",`<p>TuneBloom-Py</p><p style="color:#9aa">Python port of TuneBloom (BFSAR editor for Wii U).</p>`,[["OK"]]);
 if(a==="sys")toast("System Window : non porté");}

/* ---------- dialogs ---------- */
function dlg(title,body,btns){return new Promise(res=>{const m=$("modal");m.innerHTML=`<div class="dlg"><h3>${title}</h3><div class="bd">${body}</div><div class="ft">${btns.map((b,i)=>`<button class="btn" data-i="${i}">${b[0]}</button>`).join("")}</div></div>`;m.classList.add("on");
 m.querySelectorAll("[data-i]").forEach(b=>b.onclick=()=>{m.classList.remove("on");res(+b.dataset.i)})})}
async function pathDialog(title,start,cb,pick="file"){
 let cur=start&&start.includes("/")||start.includes("\\")?start.replace(/[\\/][^\\/]*$/,""):"";let name=start?start.split(/[\\/]/).pop():"";let sel=null;
 const m=$("modal");
 async function draw(p){const d=await jget("fs?path="+encodeURIComponent(p||""));cur=d.path;
  m.innerHTML=`<div class="dlg"><h3>${title}</h3><div class="bd"><div class="crow"><input id="dp" class="f" style="flex:1" value="${esc(cur)}"><button class="btn" id="dg">Go</button></div>
  <div class="fl" style="height:330px;overflow:auto;background:#0c0c16;padding:3px"><div class="e" data-up="1">${IC.folder} ..</div>${d.entries.map(e=>`<div class="e" data-n="${esc(e.name)}" data-d="${e.dir?1:0}">${e.dir?IC.folder:IC.file} ${esc(e.name)}</div>`).join("")}</div>
  <div class="crow" style="margin-top:8px"><span class="lab">File</span><input id="dn" class="f" style="flex:1" value="${esc(name)}"></div></div><div class="ft"><button class="btn" id="dc">Cancel</button><button class="btn" id="dok">OK</button></div></div>`;m.classList.add("on");
  $("dg").onclick=()=>draw($("dp").value);$("dc").onclick=()=>m.classList.remove("on");
  m.querySelector("[data-up]").onclick=()=>draw(d.parent);
  m.querySelectorAll("[data-n]").forEach(e=>{e.onclick=()=>{m.querySelectorAll(".e").forEach(x=>x.classList.remove("sel"));e.classList.add("sel");if(e.dataset.d!=="1")$("dn").value=e.dataset.n};
   e.ondblclick=()=>{const full=cur.replace(/[\\/]$/,"")+(cur.includes("\\")?"\\":"/")+e.dataset.n;if(e.dataset.d==="1")draw(full);else{m.classList.remove("on");cb(full)}}});
  $("dok").onclick=()=>{const n=$("dn").value;if(!n)return;m.classList.remove("on");cb(cur.replace(/[\\/]$/,"")+(cur.includes("\\")?"\\":"/")+n)}};
 draw(cur)}
function openDialog(){pathDialog("Open BFSAR","",async p=>{try{await jpost("open",{path:p});S.tabs=[];S.tab="info";S.cat="allsounds";await refreshState();await loadCat("allsounds")}catch(e){toast(e.message)}})}

/* ---------- état ---------- */
async function refreshState(){S.st=await jget("state");drawAll()}
async function loadCat(c){S.cat=c;S.tab="info";S.sel=null;S.props=[];S.search="";S.showSearch=false;
 if(c==="info"||!S.st.open){S.rows=[];drawAll(true);return}
 S.rows=await jget("list?cat="+c);drawAll(true)}
async function select(i){S.sel=i;S.props=await jget(`item?cat=${S.cat}&i=${i}`);drawAll()}

/* ---------- panneaux ---------- */
function drawLeft(){
 $("left").innerHTML=`<div class="strip"><div class="tab act">${ic(IC.folder)} Project</div><div class="menuarrow">▾</div></div><div class="body nav">${NAV.map(n=>n==="-"?"<hr>":`<div class="it${S.cat===n[0]?" sel":""}" data-c="${n[0]}">${ic(n[2])}<span>${n[1]}</span></div>`).join("")}</div>`;
 $("left").querySelectorAll("[data-c]").forEach(e=>e.onclick=()=>loadCat(e.dataset.c))}
function visibleRows(){const q=S.search.toLowerCase();return q?S.rows.filter(r=>r.name.toLowerCase().includes(q)):S.rows}
function drawCenter(){
 const _sc=SCROLLERS.slice(0,3).map(q=>{const e=document.querySelector(q);return [q,e?e.scrollTop:0]});
 const tabs=[`<div class="tab ${S.tab==="info"?"act":""}" data-t="info">${ic(IC.pen)} Info</div>`].concat(S.tabs.map(t=>`<div class="tab ${S.tab===t.id?"act":""}" data-t="${t.id}">${ic(IC.file)} ${esc(t.title)}</div>`));
 const close=S.tab!=="info"?`<div class="menuarrow">▾ &nbsp;<span class="i" id="tclose" style="cursor:pointer">${IC.x}</span></div>`:`<div class="menuarrow">▾</div>`;
 let body="";
 if(S.tab==="info")body=infoBody();else{const t=S.tabs.find(t=>t.id===S.tab);body=t?(t.type==="bank"?bankBody():seqBody()):""}
 $("center").innerHTML=`<div class="strip">${tabs.join("")}${close}</div>${body}`;
 $("center").querySelectorAll("[data-t]").forEach(e=>e.onclick=()=>{S.tab=e.dataset.t;S.rtab=S.tab==="info"?0:(S.tabs.find(t=>t.id===S.tab).type==="seq"?1:0);drawAll(true)});
 const tc=$("tclose");if(tc)tc.onclick=()=>{S.tabs=S.tabs.filter(t=>t.id!==S.tab);S.tab="info";S.rtab=0;drawAll(true)};
 if(S.tab==="info")bindInfo();else if(S.tabs.find(t=>t.id===S.tab).type==="bank")bindBank();else bindSeq();
 _sc.forEach(([q,v])=>{const e=document.querySelector(q);if(e&&v)e.scrollTop=v})}
function infoBody(){
 if(!S.st.open)return `<div class="body dropzone">No project open. Use <b>File &gt; Open</b> to load a .bfsar file.</div>`;
 if(S.cat==="info")return `<div class="body prop"><div class="prow"><span class="lab">Path</span></div><div class="prow"><div class="w" style="width:100%"><div class="fld ro">${esc(S.st.path||"")}</div></div></div>
  <div class="prow"><div class="w"><div class="fld ro">0x${(S.st.version>>>0).toString(16).padStart(8,"0")}</div></div><span class="lab">Version</span></div>${S.st.dirty?'<div class="prow"><span class="lab">* Unsaved changes</span></div>':""}</div>`;
 const rows=visibleRows();
 const search=S.showSearch?`<div class="search"><input type="text" id="q" placeholder="Search..." value="${esc(S.search)}"><button class="btn" id="qa">Aa</button><button class="btn lc" id="qx">${IC.x}</button></div>`:"";
 const snd=["allsounds","stream","wave","seq","wavefiles"].includes(S.cat);
 return `${search}<div class="body rows${snd?"":" plain"}" id="rows">${rows.map(r=>`<div class="r${S.sel===r.i?" sel":""}" data-i="${r.i}">${snd?`<div class="pbtn" data-p="${r.i}">${IC.play}</div><span class="ico i">${ICON_FOR[r.icon]||IC.file}</span>`:""}<span>[${r.i}]&nbsp;${esc(r.name)}</span>${S.playing&&S.playing.key===S.cat+":"+r.i?`<i class="i" style="margin-left:6px;color:#9fc">\ue1ab</i>`:""}</div>`).join("")}</div>
  ${S.cat==="stream"||(S.cat==="allsounds"&&sel1()==="stream")?tracksPane():""}`}
function sel1(){const r=S.rows.find(r=>r.i===S.sel);return r&&r.icon}
function tracksPane(){return `<div style="border-top:2px solid #7d7d82;height:150px;padding:6px 8px;line-height:24px"><div>[0]&nbsp;Track</div><div>[1]&nbsp;Track</div></div>`}
function bindInfo(){
 const rows=$("rows");if(!rows)return;
 rows.querySelectorAll(".r").forEach(e=>{const i=+e.dataset.i;e.onclick=ev=>{if(ev.target.closest("[data-p]"))return;select(i)};
  e.ondblclick=()=>openEditor(i);if(RENAMABLE.includes(S.cat))e.oncontextmenu=ev=>ctxMenu(ev,i)});
 rows.querySelectorAll("[data-p]").forEach(b=>b.onclick=ev=>{ev.stopPropagation();play(S.cat+":"+b.dataset.p,b.dataset.p)});
 document.onkeydown=ev=>{if((ev.ctrlKey||ev.metaKey)&&ev.key==="f"){ev.preventDefault();S.showSearch=true;drawCenter();const q=$("q");q&&q.focus()}if(ev.key==="Escape"&&S.showSearch){S.showSearch=false;S.search="";drawCenter()}};
 const q=$("q");if(q){q.oninput=()=>{S.search=q.value;const p=q.selectionStart;drawCenter();const n=$("q");n.focus();n.setSelectionRange(p,p)};$("qx").onclick=()=>{S.showSearch=false;S.search="";drawCenter()}}}
async function openEditor(i){
 const r=S.rows.find(r=>r.i===i);if(!r)return;
 if(S.cat==="banks"){const id="bank"+i;if(!S.tabs.find(t=>t.id===id)){const d=await jget("bank?i="+i);S.tabs.push({id,type:"bank",bank:i,title:`[${i}] ${r.name}`,data:d,ins:0,reg:0})}S.tab=id;S.rtab=0}
 else if(S.cat==="bankfiles"){toast("Utilisez la catégorie Banks pour éditer une banque")}
 else if((S.cat==="seq"||S.cat==="allsounds")&&r.icon==="seq"||S.cat==="seqfiles"){const id="seq"+S.cat+i;if(!S.tabs.find(t=>t.id===id)){try{const d=await jget(`seq?kind=${S.cat==="seqfiles"?"file":"sound"}&i=${i}`);S.tabs.push({id,type:"seq",kind:S.cat==="seqfiles"?"file":"sound",i,title:`[${i}] ${r.name}`,data:d,follow:true,trail:true,edit:false,text:"",track:0,tracks:null})}catch(e){return toast(e.message)}}S.tab=id;S.rtab=1}
 drawAll(true)}

/* ---------- menu contextuel (Replace / Export), comme l'original ---------- */
const RENAMABLE=["wavefiles","allsounds","stream","wave","seq","allsets","wavesets","seqsets","banks","warcs","groups","players"];
async function reloadKeep(sel){S.rows=await jget("list?cat="+S.cat);S.st=await jget("state");if(sel!==undefined&&sel!==null){S.sel=sel;try{S.props=await jget(`item?cat=${S.cat}&i=${sel}`)}catch(e){}}drawAll()}
async function doRename(i){
 const r=S.rows.find(r=>r.i===i);const n=prompt("New name (ASCII, no spaces)",r.name);if(!n||n===r.name)return;
 try{await jpost("rename",{cat:S.cat,i,name:n});await reloadKeep(i);toast("Renamed")}catch(e){toast(e.message)}}
async function doDuplicate(i){
 const r=S.rows.find(r=>r.i===i);const n=prompt("Name of the copy",r.name+"_COPY");if(!n)return;
 try{const x=await jpost("duplicate",{i,name:n});await reloadKeep(x.index);toast("Sound duplicated")}catch(e){toast(e.message)}}
function addStreamFlow(){
 pathDialog("Add Stream Sound — audio (.wav / .bfstm)","",async p=>{
  const base=p.split(/[\\/]/).pop().replace(/\.[^.]*$/,"").replace(/[^A-Za-z0-9_]/g,"_");
  const name=prompt("Sound name (ASCII, no spaces)","STM_"+base.toUpperCase());if(!name)return;
  let loop=null;if(/\.wav$/i.test(p)){const v=prompt("Loop start (sample index, empty = no loop)","");if(v!==null&&v.trim()!=="")loop=parseInt(v)}
  toast("Encoding… (long files can take a few minutes)");
  try{const r=await jpost("addstream",{name,path:p,loop});S.cat="stream";S.tab="info";S.rows=await jget("list?cat=stream");S.st=await jget("state");S.sel=r.index;S.props=await jget(`item?cat=stream&i=${r.index}`);drawAll(true);
   const el=document.querySelector(`#rows .r[data-i="${r.index}"]`);if(el)el.scrollIntoView({block:"center"});toast(r.note)}catch(e){toast(e.message)}})}
function tmplFor(icon){const r=S.rows.find(r=>r.i===S.sel);return r&&r.icon===icon?S.sel:null}
async function afterAdd(cat,r){S.cat=cat;S.tab="info";S.rows=await jget("list?cat="+cat);S.st=await jget("state");S.sel=r.index;S.props=await jget(`item?cat=${cat}&i=${r.index}`);drawAll(true);
 const el=document.querySelector(`#rows .r[data-i="${r.index}"]`);if(el)el.scrollIntoView({block:"center"});toast(r.note)}
function addWaveFlow(){
 pathDialog("Add Wave Sound — audio (.wav / .bfwav)","",async p=>{
  const base=p.split(/[\\/]/).pop().replace(/\.[^.]*$/,"").replace(/[^A-Za-z0-9_]/g,"_");
  const name=prompt("Sound name (ASCII, no spaces)","SE_"+base.toUpperCase());if(!name)return;
  toast("Encoding…");try{const r=await jpost("addwave",{name,path:p,template:tmplFor("wave")});await afterAdd("wave",r)}catch(e){toast(e.message)}})}
async function addSeqFlow(){
 const name=prompt("Sound name (ASCII, no spaces)","SE_NEW_SEQUENCE");if(!name)return;
 const code="    prg 0\n    cn4 100, 24\n    wait 24\n    fin";
 try{const r=await jpost("addseq",{name,code,template:tmplFor("seq")});await afterAdd("seq",r);await openEditor(r.index);toast("Edit the MML (double-click the code), then Ctrl+S")}catch(e){toast(e.message)}}
function ctxWave(ev,i){
 ev.preventDefault();document.querySelectorAll(".dd.ctx").forEach(e=>e.remove());
 const d=document.createElement("div");d.className="dd ctx";d.style.left=ev.clientX+"px";d.style.top=ev.clientY+"px";
 d.innerHTML=`<div data-a="wreplace">Replace</div><div data-a="wexport">Export WAV</div><div data-a="wexportraw">Export BFWAV</div><div data-a="wloop">Edit loop…</div>`;document.body.appendChild(d);
 const refresh=async m=>{S.st=await jget("state");S.sel=i;S.props=await jget(`item?cat=wavefiles&i=${i}`);drawAll();if(m)toast(m)};
 d.onclick=async e=>{const a=e.target.dataset.a;d.remove();
  const dl=f=>{const l=document.createElement("a");l.href=`/api/waveexport?i=${i}&fmt=${f}`;l.download="";document.body.appendChild(l);l.click();l.remove()};
  if(a==="wexport")dl("wav");if(a==="wexportraw")dl("bfwav");
  if(a==="wloop"){const v=prompt("Loop start (sample index; empty = no loop)","");if(v===null)return;
   try{const r=await jpost("waveloop",{i,loop:v.trim()===""?null:parseInt(v)});await refresh(r.note)}catch(er){toast(er.message)}}
  if(a==="wreplace")pathDialog("Replace wave with (.wav / .bfwav)","",async p=>{let loop=null;if(/\.wav$/i.test(p)){const v=prompt("Loop start (sample index, empty = no loop)","");if(v!==null&&v.trim()!=="")loop=parseInt(v)}
   toast("Encoding…");try{const r=await jpost("wavereplace",{i,path:p,loop});await refresh(r.note)}catch(er){toast(er.message)}})};
 setTimeout(()=>document.addEventListener("click",()=>d.remove(),{once:true}),0)}
function ctxMenu(ev,i){
 ev.preventDefault();document.querySelectorAll(".dd.ctx").forEach(e=>e.remove());
 const snd=["allsounds","stream","wave","seq"].includes(S.cat);
 if(S.cat==="wavefiles"){ctxWave(ev,i);return}
 const items=[["rename","Rename"]].concat(S.cat==="warcs"?[["waveadd","Add Wave…"]]:[]).concat(snd?[["duplicate","Duplicate"],["replace","Replace"],["export","Export"],["delete","Delete"]]:[]);
 const d=document.createElement("div");d.className="dd ctx";d.style.left=ev.clientX+"px";d.style.top=ev.clientY+"px";
 d.innerHTML=items.map(([k,l])=>`<div data-a="${k}">${l}</div>`).join("");document.body.appendChild(d);
 d.onclick=async e=>{const a=e.target.dataset.a;d.remove();
  if(a==="rename")doRename(i);if(a==="duplicate")doDuplicate(i);
  if(a==="waveadd")pathDialog("Add wave to archive (.wav / .bfwav)","",async p=>{toast("Encoding…");try{const r=await jpost("waveadd",{warc:i,path:p});S.st=await jget("state");S.props=await jget(`item?cat=warcs&i=${i}`);drawAll();toast(r.note)}catch(e){toast(e.message)}});
  if(a==="delete"){const r=S.rows.find(r=>r.i===i);if(confirm("Delete sound "+r.name+" ?\nLater sounds are renumbered; its audio file stays in the archive."))
   try{const x=await jpost("delete",{i});S.sel=null;S.props=[];S.rows=await jget("list?cat="+S.cat);S.st=await jget("state");drawAll();toast("Deleted "+x.name)}catch(e){toast(e.message)}}
  if(a==="export"){const l=document.createElement("a");l.href="/api/export?i="+i;l.download="";document.body.appendChild(l);l.click();l.remove()}
  if(a==="replace")pathDialog("Replace with (.wav / .bfstm / .bfwav)","",async p=>{
   let loop=null;if(/\.wav$/i.test(p)){const v=prompt("Loop start (sample index, empty = no loop)","");if(v!==null&&v.trim()!=="")loop=parseInt(v)}
   toast("Encoding…");try{const r=await jpost("replace",{i,path:p,loop});S.st=await jget("state");toast(r.note);drawAll()}catch(e){toast(e.message)}})};
 setTimeout(()=>document.addEventListener("click",()=>d.remove(),{once:true}),0)}
/* ---------- propriétés ---------- */
function drawRight(){
 const tabs=["Properties -…","Player Param…","Sequence Var…"],icons=[IC.tprops,IC.set2,IC.bin];
 let body="";const cur=S.tab==="info"?null:S.tabs.find(t=>t.id===S.tab);
 if(!cur)body=propsBody();else if(cur.type==="bank")body=bankProps(cur);else body=S.rtab===1?paramBody():propsBody();
 $("right").innerHTML=`<div class="strip">${tabs.map((t,i)=>`<div class="tab ${S.rtab===i?"act":"dimt"}" data-r="${i}">${ic(icons[i])} ${t}</div>`).join("")}<div class="menuarrow">▾</div></div><div class="body prop">${body}</div>`;
 $("right").querySelectorAll("[data-r]").forEach(e=>e.onclick=()=>{S.rtab=+e.dataset.r;drawRight()});
 bindProps();if(cur&&cur.type==="bank")bindBankProps(cur)}
function propsBody(){
 if(!S.st.open||S.sel===null||S.cat==="info")return "";
 return S.props.map((p,n)=>{
  if(p.t==="section")return `<div class="sec"><span style="font-size:10px">▶</span>${esc(p.label)}</div>`;
  if(p.t==="tabs")return `<div class="subtabs">${p.tabs.map((t,i)=>`<div class="${i===p.active?"act":""}">${t}</div>`).join("")}</div>`;
  if(p.t==="soundlist")return `<div style="height:calc(100% - 215px);min-height:200px;overflow:auto;border:1px solid #2c2c3c;margin-top:6px" class="rows">${p.items.map(r=>`<div class="r"><div class="pbtn" data-sp="${r.i}">${IC.play}</div><span>[${r.i}]&nbsp;${esc(r.name)}</span></div>`).join("")}</div>`;
  let w="";
  if(p.t==="text")w=`<div class="fld ro">${esc(p.v)}</div>`;
  else if(p.t==="num")w=`<input class="f fld" data-k="${p.key||""}" value="${p.v}" ${p.ro?"readonly":""} style="${p.ro?"color:#c8c8cf":""}"><button class="btn" data-d="-1" data-n="${n}">-</button><button class="btn" data-d="1" data-n="${n}">+</button>`;
  else if(p.t==="combo")w=`<div class="fld ro" style="flex:1">${esc(p.v)}</div><div class="btn" style="width:26px;background:#2a4f7a" ${p.cyc?`data-pn="${p.key}" data-pv="${(p.cur+1)%p.n}"`:""}>▼</div>${p.nav?`<div class="btn" ${p.key?`data-pn="${p.key}" data-pv="${(p.cur-1+p.n)%p.n}"`:""}>◀</div><div class="btn" ${p.key?`data-pn="${p.key}" data-pv="${(p.cur+1)%p.n}"`:""}>▶</div>`:""}`;
  else if(p.t==="check")return `<div class="prow ${p.dim?"dis":""}"><div class="chk">${p.v?IC.check:""}</div><span class="lab" style="color:${p.dim?"#6a6a78":"inherit"}">${esc(p.label)}</span></div>`;
  else if(p.t==="slider")w=p.key?`<input class="f fld" data-k="${p.key}" style="text-align:center" value="${(+p.v).toFixed(3)}">`:`<div class="slider"><div class="th"></div>${(+p.v).toFixed(3)}</div>`;
  return `<div class="prow"><div class="w">${w}</div><span class="lab">${esc(p.label)}</span></div>`}).join("")}
function bindProps(){
 $("right").querySelectorAll("[data-k]").forEach(inp=>{if(!inp.dataset.k)return;const commit=async v=>{try{await jpost("set",{cat:S.cat,i:S.sel,key:inp.dataset.k,value:v});S.props=await jget(`item?cat=${S.cat}&i=${S.sel}`);S.st=await jget("state");drawRight();drawCenter()}catch(e){toast(e.message)}};
  inp.onchange=()=>commit(inp.value);
  inp.parentElement.querySelectorAll("[data-d]").forEach(b=>b.onclick=()=>commit(+inp.value+ +b.dataset.d))});
 $("right").querySelectorAll("[data-pn]").forEach(b=>b.onclick=async()=>{try{await jpost("set",{cat:S.cat,i:S.sel,key:b.dataset.pn,value:+b.dataset.pv});S.props=await jget(`item?cat=${S.cat}&i=${S.sel}`);S.st=await jget("state");drawRight();drawCenter()}catch(e){toast(e.message)}});
 $("right").querySelectorAll("[data-sp]").forEach(b=>b.onclick=()=>play("allsounds:"+b.dataset.sp,b.dataset.sp))}
function paramBody(){return `<div style="color:#9aa;margin:4px 0">(?)</div><div class="subtabs"><div>Basic</div><div class="act">Track</div><div>Send</div></div>
 <div class="btn lc" style="margin-bottom:6px">${IC.rst}</div>`+Array.from({length:16},(_,i)=>`<div class="trk"><div class="fld ro">1.000</div><span class="lab" style="width:78px;white-space:nowrap">Track ${i}</span><div class="tb"><i style="width:${[40,12,8,10,20,50,10,45,10,30,40,30,40,10,12,20][i]}%"></i><b>02/18</b></div></div>`).join("")}

/* ---------- éditeur de banque ---------- */
const WHITE=[0,2,4,5,7,9,11],BLK={1:1,3:2,6:4,8:5,10:6};
/* centre horizontal de la touche k (en largeurs de touche blanche) : blanche = milieu de sa case, noire = frontière entre deux blanches */
function cx(k){const o=Math.floor(k/12),n=k%12;return (o*7+(n in BLK?BLK[n]:WHITE.indexOf(n)+0.5))}
function edge(k){return k<=0?0:k>=128?cx(127)+0.5:(cx(k-1)+cx(k))/2}   /* frontière entre les touches k-1 et k */
function bankBody(){
 const t=S.tabs.find(t=>t.id===S.tab);const ins=t.data.instruments;
 return `<div class="body ed" style="display:flex;flex-direction:column"><div class="ilist" style="margin:8px 6px 0;height:392px;overflow:auto;border:1px solid #20202e">${ins.map((x,i)=>`<div class="r${t.ins===i?" sel":""}" data-ins="${i}" style="padding-left:8px">[${x.p}]&nbsp;Instrument</div>`).join("")}</div>
  <div style="margin:10px 6px 0;border:1px solid #20202e;flex:1;padding-top:3px"><div class="kbd" id="kbd"></div>
  <div style="margin:2px 8px;display:grid;grid-template-columns:110px 100px 100px;gap:6px 2px;align-items:center"><span>Key</span><div class="fld ro" id="kk1">–</div><div class="fld ro" id="kk2">–</div><span>Velocity</span><div class="fld ro" id="kv1">–</div><div class="fld ro" id="kv2">–</div><span style="width:100px">Original Key</span><div class="fld ro" id="kok">–</div></div></div></div>`}
function noteName(k){const n=["cn","cs","dn","ds","en","fn","fs","gn","gs","an","as","bn"][k%12],o=Math.floor(k/12)-1;return n+(o<0?"m1":o)}
function bindBank(){
 const t=S.tabs.find(t=>t.id===S.tab);if(!t)return;
 $("center").querySelectorAll("[data-ins]").forEach(e=>e.onclick=()=>{t.ins=+e.dataset.ins;t.reg=0;drawAll()});
 const k=$("kbd");if(!k)return;const W=k.clientWidth/75,regs=t.data.instruments[t.ins].regions;k.innerHTML="";
 regs.forEach((r,n)=>{const d=document.createElement("div");d.className="reg"+(n===t.reg?" sel":"");const x0=edge(r.kmin)*W,x1=edge(r.kmax+1)*W;
  d.style.left=x0+"px";d.style.width=Math.max(6,x1-x0)+"px";d.textContent=r.name;d.onclick=()=>{t.reg=n;drawAll()};k.appendChild(d)});
 for(let o=0;o<11;o++)for(const n of WHITE){const kk=o*12+n;if(kk>127)break;const d=document.createElement("div");d.className="wk";d.dataset.k=kk;d.onclick=()=>playNote(t,kk);d.style.left=(cx(kk)-0.5)*W+"px";d.style.width=W+"px";k.appendChild(d)}
 for(let o=0;o<11;o++)for(const n in BLK){const kk=o*12+ +n;if(kk>127)break;const d=document.createElement("div");d.className="bk";d.dataset.k=kk;d.onclick=()=>playNote(t,kk);d.style.left=(cx(kk)-0.3)*W+"px";d.style.width=W*.6+"px";k.appendChild(d)}
 for(let o=0;o<11;o++){const d=document.createElement("div");d.className="oct";d.style.left=(o*7*W+3)+"px";d.textContent=o;k.appendChild(d)}
 const r=regs[t.reg];if(r){$("kk1").textContent=r.kmin;$("kk2").textContent=r.kmax;$("kv1").textContent=r.vmin;$("kv2").textContent=r.vmax;$("kok").textContent=noteName(r.key)}}
function bankProps(t){
 const ins=t.data.instruments[t.ins],r=ins.regions[t.reg];
 const prg=`<div class="prow"><div class="w"><div class="fld ro">${ins.p}</div><div class="btn">-</div><div class="btn">+</div></div><span class="lab">Program Number</span></div>`;
 if(!r)return prg;
 const ed=f=>r.editable.includes(f)||f.startsWith("adshr")&&r.editable.includes("adshr");
 const num=(v,l,f)=>`<div class="prow"><div class="w"><input class="f fld" ${ed(f)?`data-bf="${f}"`:"readonly"} value="${v}"><button class="btn" ${ed(f)?`data-bf="${f}" data-bd="-1"`:""}>-</button><button class="btn" ${ed(f)?`data-bf="${f}" data-bd="1"`:""}>+</button></div><span class="lab">${l}</span></div>`;
 const interp=["Nearest Neighbor","Linear","Polyphase (4-point)","Polyphase (6-point)"];
 return `${prg}<div class="sep"></div>
 <div class="prow"><div class="w"><div class="fld ro" style="flex:1">[${r.wave}] ${esc(r.name)}</div><div class="btn">▼</div><div class="btn">◀</div><div class="btn">▶</div></div><span class="lab">Wave File</span><div class="btn lc">${IC.ext}</div></div>
 ${num(r.key,"Original Key","original_key")}${num(r.vol,`Volume (${(r.vol/127).toFixed(3)})`,"volume")}${num(r.pan,`Pan (${((r.pan-64)/64).toFixed(3)})`,"pan")}
 <div class="prow"><div class="w"><input class="f fld" style="text-align:center" ${ed("pitch")?'data-bf="pitch"':"readonly"} value="${r.pitch.toFixed(3)}"></div><span class="lab">Pitch</span></div>
 <div class="prow ${ed("ignore_note_off")?"":"dis"}"><div class="chk" ${ed("ignore_note_off")?'data-bf="ino" style="cursor:pointer"':""}>${r.ino?IC.check:""}</div><span class="lab">Ignore Note Off (Percussion Mode) (?)</span></div>
 ${num(r.kg,"Key Group","key_group")}<div class="prow"><div class="w"><div class="fld ro" style="flex:1">${interp[r.interp]||r.interp}</div><div class="btn" data-bf="interp" data-cyc="1">▼</div></div><span class="lab">Interpolation Type</span></div>
 ${["Attack","Decay","Sustain","Hold","Release"].map((l,i)=>num(r.adshr[i],l,"adshr"+i)).join("")}`}
async function bankSet(t,field,value){
 try{const r=await jpost("bankset",{bank:t.bank,ins:t.ins,reg:t.reg,field,value});t.data=r;S.st=await jget("state");drawAll()}catch(e){toast(e.message)}}
function bindBankProps(t){
 const r=t.data.instruments[t.ins].regions[t.reg];if(!r)return;
 document.querySelectorAll("#right [data-bf]").forEach(el=>{const f=el.dataset.bf;
  if(el.tagName==="INPUT")el.onchange=()=>bankSet(t,f,f==="pitch"?parseFloat(el.value):parseInt(el.value));
  else if(el.dataset.bd){const inp=el.parentElement.querySelector("input");el.onclick=()=>bankSet(t,f,parseInt(inp.value)+parseInt(el.dataset.bd))}
  else if(f==="ino")el.onclick=()=>bankSet(t,"ignore_note_off",r.ino?0:1);
  else if(el.dataset.cyc)el.onclick=()=>bankSet(t,"interp",((r.interp||0)+1)%4)})}
/* ---------- éditeur de séquence ---------- */
function hl(t){return esc(t).replace(/ /g,'<span class="sp">\u00b7</span>').replace(/(-?\b\d+\b)/g,'<span class="num">$1</span>')}
function seqBody(){
 const t=S.tabs.find(t=>t.id===S.tab),d=t.data;
 const combo=(v,l,extra="")=>`<div class="crow"><div class="fld ro" style="flex:1">${esc(v)}</div><div class="btn">▼</div><div class="btn">◀</div><div class="btn">▶</div><span class="lab" style="width:60px">${l}</span>${extra}</div>`;
 let h=`<div class="body ed" style="display:flex;flex-direction:column;overflow:hidden"><div class="opts" style="padding:6px 8px 0"><div style="color:#cfd;margin-bottom:6px">Options</div>${d.banks.map((b,i)=>combo(b,"Bank "+i,`<div class="btn lc">${IC.file}</div>`)).join("")}
 <div class="crow"><div class="fld ro" style="flex:1">${esc(d.start_label)}</div><div class="btn">▼</div><span class="lab">Start Label</span></div>
 <div class="mmlbar" style="padding:2px 0"><div class="pbtn" style="width:28px;height:28px" id="seqplay">${IC.play}</div><div class="btn lc" id="seqapply" title="Compile & apply (Ctrl+S)" style="width:28px;height:28px;${t.edit?"background:#3d8f4f":""}">${IC.save}</div><div class="chk" id="chkfollow" style="width:24px;height:24px;font-size:15px;cursor:pointer">${t.follow?IC.check:""}</div><span>Follow</span><select id="trksel" class="f" style="flex:1;height:28px;padding:0 6px">${(t.tracks||Array.from({length:16},(_,k)=>k)).map(k=>`<option value="${k}" ${k===t.track?"selected":""}>Track ${k}</option>`).join("")}</select><span>Track</span><div class="chk" id="chktrail" style="width:24px;height:24px;font-size:15px;cursor:pointer">${t.trail?IC.check:""}</div><span>Trail</span></div></div>`;
 if(t.edit)return h+`<textarea id="mml" class="code" spellcheck="false" style="border:0;outline:0;resize:none;background:var(--bg);color:#e6e6ea;font:inherit;line-height:20px;padding:0 0 0 12px;white-space:pre;tab-size:4">${esc(t.text)}</textarea></div>`;
 h+=`<div class="code" id="code">${d.lines.map((l,n)=>l.k==="label"?`<div class="ln lbl"><span class="n"></span><span class="lbl2">${esc(l.t)}</span></div>`:`<div class="ln" data-o="${l.o}"><span class="n">${l.o}</span><span class="kw"><span class="sp">\u00b7\u00b7\u00b7\u00b7</span>${hl(l.t)}</span></div>`).join("")}</div></div>`;return h}
function seqText(d){return d.lines.map(l=>l.k==="label"?l.t:"    "+l.t).join("\n")}
async function seqApply(t){
 const ta=$("mml");if(!ta)return;
 try{const r=await jpost("seqapply",{kind:t.kind,i:t.i,text:ta.value});t.data=r;t.edit=false;S.st=await jget("state");
  if(r.warnings&&r.warnings.length)toast(r.warnings.join("\n"));else toast("Séquence compilée et appliquée");drawAll()}
 catch(e){const m=/ligne (\d+)/.exec(e.message);toast(e.message);if(m){const n=+m[1]-1,lines=ta.value.split("\n");let pos=0;for(let k=0;k<n;k++)pos+=lines[k].length+1;ta.focus();ta.setSelectionRange(pos,pos+(lines[n]||"").length);ta.scrollTop=Math.max(0,(n-5)*20)}}}
function bindSeq(){const b=$("seqplay");if(!b)return;const t=S.tabs.find(t=>t.id===S.tab);
 const ts=$("trksel");if(ts)ts.onchange=()=>{t.track=+ts.value};
 const cf=$("chkfollow");if(cf)cf.onclick=()=>{t.follow=!t.follow;cf.textContent=t.follow?IC.check:""};
 const ctl=$("chktrail");if(ctl)ctl.onclick=()=>{t.trail=!t.trail;ctl.textContent=t.trail?IC.check:""};
 const ap=$("seqapply");if(ap)ap.onclick=()=>{if(t.edit)seqApply(t);else{t.edit=true;t.text=seqText(t.data);drawCenter()}};
 const code=$("code");if(code)code.ondblclick=()=>{t.edit=true;t.text=seqText(t.data);drawCenter();const ta=$("mml");if(ta)ta.focus()};
 const ta=$("mml");if(ta){ta.onkeydown=ev=>{if((ev.ctrlKey||ev.metaKey)&&ev.key==="s"){ev.preventDefault();seqApply(t)}if(ev.key==="Tab"){ev.preventDefault();const s0=ta.selectionStart;ta.setRangeText("    ",s0,ta.selectionEnd,"end")}if(ev.key==="Escape"){t.edit=false;drawCenter()}}}
b.onclick=()=>{const key=t.id;play(key,t.id.replace(/^seq(allsounds|seq|seqfiles)/,""),t.id.includes("seqfiles")?null:"sound")}}

/* ---------- lecteur ---------- */
const A=()=>$("audio");
function fmt(s){if(!isFinite(s))s=0;const m=Math.floor(s/60);return String(m).padStart(2,"0")+":"+(s%60).toFixed(3).padStart(6,"0")}
function drawPlayer(){
 const a=A(),playing=!a.paused&&a.src;
 $("player").innerHTML=`<div class="strip"><div class="tab act">${ic(IC.music)} Player</div><div class="menuarrow">▾</div></div><div class="ctl"><div class="pb" id="pp">${playing?IC.pause:IC.play}</div><div class="pb" id="ps">${IC.sq}</div><span class="tm" id="tcur">${fmt(a.currentTime||0)}</span>
  <div class="bar" id="bar"><div class="fill" id="fill" style="width:${a.duration?100*a.currentTime/a.duration:0}%"></div>${a.duration&&S.loop&&S.loop.length===2?`<div class="mk" style="left:${100*S.loop[0]/a.duration}%;background:#18c24a"></div><div class="mk" style="left:calc(${100*S.loop[1]/a.duration}% - 2px);background:#d22"></div>`:""}</div><span class="tm" id="ttot" style="text-align:right">${fmt(a.duration||0)}</span><i class="i" style="font-size:18px">${IC.vol2}</i></div>`;
 $("pb");$("pp").onclick=()=>{if(!a.src)return;a.paused?a.play():a.pause()};$("ps").onclick=()=>{a.pause();a.currentTime=0;S.playing=null;drawPlayer();drawCenter()};
 $("bar").onclick=ev=>{if(a.duration){const r=$("bar").getBoundingClientRect();a.currentTime=a.duration*(ev.clientX-r.left)/r.width}}}
async function play(key,i,kind){
 const a=A();try{const k=kind||(S.cat==="wavefiles"?"wavefile":"sound");
  const r=await api(`audio?kind=${k}&i=${i}`);const blob=await r.blob();if(k==="sound")loadTrace(i);S.loop=(r.headers.get("X-Loop")||"").split(",").map(parseFloat).filter(x=>!isNaN(x));a.src=URL.createObjectURL(blob);await a.play();S.playing={key};drawPlayer();drawCenter()}catch(e){toast(e.message)}}
async function loadTrace(i){
 S.trace=null;try{const d=await jget(`trace?kind=sound&i=${i}`);if(!d.trace.length)return;const by={};
  for(const [t,k,o] of d.trace){(by[k]||(by[k]={t:[],o:[]})).t.push(t);by[k].o.push(o)}S.trace={by,tracks:d.tracks};
  const tab=S.tabs.find(x=>x.id===S.tab);if(tab&&tab.type==="seq"){tab.tracks=d.tracks;if(!d.tracks.includes(tab.track))tab.track=d.tracks[0];const sel=$("trksel");
   if(sel)sel.innerHTML=d.tracks.map(k=>`<option value="${k}" ${k===tab.track?"selected":""}>Track ${k}</option>`).join("")}}catch(e){S.trace=null}}
function followTick(){
 try{const tab=S.tabs.find(x=>x.id===S.tab),a=A();
  if(tab&&tab.type==="seq"&&!tab.edit&&S.trace&&!a.paused){const code=$("code"),bt=S.trace.by[tab.track];
   if(code&&bt){const now=a.currentTime;let lo=0,hi=bt.t.length;while(lo<hi){const m=(lo+hi)>>1;if(bt.t[m]<=now)lo=m+1;else hi=m}
    const last=lo-1;const win=tab.trail?1.0:0.0;let first=last;while(first>0&&bt.t[first-1]>=now-win)first--;
    const on=new Set(),cur=last>=0?bt.o[last]:-1;for(let k=Math.max(0,first);k<=last;k++)on.add(bt.o[k]);
    code.querySelectorAll(".ln[data-o]").forEach(e=>{const o=+e.dataset.o;e.classList.toggle("cur",o===cur);e.classList.toggle("trail",o!==cur&&on.has(o))});
    if(tab.follow&&cur>=0){const el=code.querySelector(`.ln[data-o="${cur}"]`);if(el){const y=el.offsetTop-code.clientHeight/2;if(Math.abs(code.scrollTop-y)>code.clientHeight*0.35)code.scrollTop=y}}}}}catch(e){}
 requestAnimationFrame(followTick)}
requestAnimationFrame(followTick);
A().addEventListener("timeupdate",()=>{const a=A();const f=$("fill");if(f){f.style.width=(a.duration?100*a.currentTime/a.duration:0)+"%";$("tcur").textContent=fmt(a.currentTime);$("ttot").textContent=fmt(a.duration)}});
A().addEventListener("ended",()=>{S.playing=null;drawPlayer();drawCenter()});
A().addEventListener("pause",drawPlayer);A().addEventListener("play",drawPlayer);

const SCROLLERS=["#rows","#code",".ilist","#right .body","#center > .body","#left .body"];
function drawAll(reset){
 const keep=reset?{}:Object.fromEntries(SCROLLERS.map(q=>{const e=document.querySelector(q);return [q,e?e.scrollTop:0]}));
 drawMenu();drawLeft();drawCenter();drawRight();drawPlayer();
 if(!reset)SCROLLERS.forEach(q=>{const e=document.querySelector(q);if(e&&keep[q])e.scrollTop=keep[q]})}
setInterval(()=>fetch('/api/ping').catch(()=>{}),4000);fetch('/api/ping').catch(()=>{});
(async()=>{drawAll();await refreshState();if(S.st.open)await loadCat("allsounds")})();
