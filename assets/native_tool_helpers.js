"use strict";
function nFirstValue(obj, keys){
  obj=obj||{};
  for(var i=0;i<keys.length;i++){
    var v=obj[keys[i]];
    if(v!=null && v!=="") return v;
  }
  return "";
}
function nMiniKvHtml(rows){
  rows=(rows||[]).filter(function(r){ return r && r[1]!=null && r[1]!==""; });
  if(!rows.length) return "";
  return '<div class="special-kv">'+rows.map(function(r){
    return '<div><span>'+nEsc(r[0])+'</span><b>'+nEsc(r[1])+'</b></div>';
  }).join("")+'</div>';
}
function nSafeLinkHtml(url, cls){
  url=String(url||"");
  var safe=url.indexOf("http://")===0 || url.indexOf("https://")===0 || url.indexOf("/api/")===0;
  return safe ? '<a class="'+cls+'" href="'+nEscAttr(url)+'" target="_blank" rel="noopener">'+nEsc(url)+'</a>'
              : '<div class="'+cls+'">'+nEsc(url)+'</div>';
}
function nSpecialToolBody(name, input){
  name=String(name||"").toLowerCase(); input=input||{};
  if(name==="sleep"){
    var dur=nFirstValue(input, ["durationMs","duration_ms","milliseconds","ms","seconds","duration"]);
    return '<div class="special-card sleep-card"><div class="special-title">'+_I('hourglass')+' Sleep</div>'+
           nMiniKvHtml([["duration", dur], ["reason", input.reason||input.message||""]])+'</div>';
  }
  if(name==="contextcompaction"){
    return '<div class="special-card compact-card"><div class="special-title">'+_I('archive')+' Context compaction</div>'+
           nMiniKvHtml([["status", input.status||input.phase||""], ["tokens", input.tokens||input.tokenCount||input.inputTokens||""], ["summary", input.summary||input.message||""]])+'</div>';
  }
  if(name==="imagegeneration"){
    var prompt=input.prompt||input.description||input.text||"";
    var imageSize=input.size || ((input.width&&input.height)?(input.width+"x"+input.height):"");
    return '<div class="special-card image-card"><div class="special-title">'+_I('sparkles')+' Image generation</div>'+
           (prompt?'<div class="special-prompt">'+nEsc(prompt)+'</div>':'')+
           nMiniKvHtml([["size", imageSize], ["model", input.model||""]])+'</div>';
  }
  if(name==="imageview"){
    var path=input.path||input.file||input.url||input.imageUrl||"";
    return '<div class="special-card image-card"><div class="special-title">'+_I('file-text')+' Image view</div>'+
           (path?nSafeLinkHtml(path, "special-path"):"")+
           nMiniKvHtml([["mime", input.mimeType||input.mime||""], ["size", input.size||""]])+'</div>';
  }
  return "";
}
function nToolInputPreview(input){
  if(!input || typeof input!=="object" || Array.isArray(input)) return "";
  var keys=Object.keys(input), shown=keys.slice(0,4);
  if(!shown.length) return "";
  return '<div class="tool-arg-preview">'+shown.map(function(k){
    var v=input[k], text=(v && typeof v==="object")?JSON.stringify(v):String(v);
    return '<div><span>'+nEsc(k)+'</span><b>'+nEsc(text.slice(0,180))+'</b></div>';
  }).join("")+(keys.length>shown.length?'<div><span>more</span><b>'+nEsc(keys.length-shown.length)+' fields</b></div>':'')+'</div>';
}
function nStructuredToolBody(name, input){
  var raw=String(name||""), lower=raw.toLowerCase();
  if(lower.indexOf(".")<0 && lower.indexOf("/")<0) return "";
  if(["webfetch","websearch","exitplanmode"].indexOf(lower)>=0) return "";
  var split=raw.indexOf(".")>=0 ? raw.split(".", 2) : raw.split("/", 2);
  var server=split[0]||"tool", tool=raw.slice((split[0]||"").length+1)||raw;
  var pretty="";
  try{ pretty=JSON.stringify(input||{}, null, 2); }catch(e){ pretty=String(input||""); }
  return '<div class="special-card mcp-card"><div class="special-title">'+_I('wrench')+' Tool call</div>'+
         nMiniKvHtml([["server", server], ["tool", tool]])+
         nToolInputPreview(input||{})+
         '<details class="tool-args"><summary>Arguments</summary><pre>'+nEsc(pretty)+'</pre></details></div>';
}
function nShellGroupKey(name){
  name=String(name||"").toLowerCase();
  return (name==="bash"||name==="powershell")?name:"";
}
function nAppendShellGroupEntry(st, b, summaryHtml, bodyHtml){
  var key=nShellGroupKey(b.name), g=st.lastToolGroup, host=nTurnCard(st);
  if(!g || g.key!==key || !g.el || !g.el.parentNode){
    var card=document.createElement("div");
    card.className="nmsg tool tool-group";
    card.innerHTML='<details><summary class="tool-group-summary"></summary><div class="tool-group-body"></div></details>';
    host.appendChild(card);
    g={key:key, el:card, count:0, summary:card.querySelector(".tool-group-summary"), body:card.querySelector(".tool-group-body"), baseSummary:summaryHtml};
    st.lastToolGroup=g;
  }
  g.count++;
  g.summary.innerHTML=g.baseSummary+' <span class="tcdesc">(x'+g.count+')</span>';
  var entry=document.createElement("div");
  entry.className="tool-entry";
  entry.dataset.tuid=b.id||"";
  entry.dataset.tname=b.name||"";
  entry.innerHTML='<div class="tool-entry-idx">#'+g.count+'</div>'+bodyHtml+'<div class="tres">Running...</div>';
  g.body.appendChild(entry);
  st.curTxt=null; nScrollBottom();
}
