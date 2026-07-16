"use strict";
function nToolResultHtml(txt){
  var _nl=String.fromCharCode(10), _lines=String(txt).split(_nl).length;
  var _resSum='Result ('+_lines+' lines)';
  return '<details class="tres-det"><summary>'+nEsc(_resSum)+'</summary><pre>'+nEsc(txt)+'</pre></details>';
}
function nCommandResultParts(txt, meta){
  var lines=String(txt==null?"":txt).split(String.fromCharCode(10));
  var exitCode=(meta && (meta.exit_code!=null ? meta.exit_code : meta.exitCode));
  var durationMs=(meta && (meta.duration_ms!=null ? meta.duration_ms : meta.durationMs));
  var bodyLines=lines.slice();
  while(bodyLines.length){
    var last=String(bodyLines[bodyLines.length-1]||"").trim(), m;
    m=/^duration ms:\s*(\d+)$/i.exec(last);
    if(m){ if(durationMs==null || durationMs==="") durationMs=Number(m[1]); bodyLines.pop(); continue; }
    m=/^exit code:\s*(-?\d+)$/i.exec(last);
    if(m){ if(exitCode==null || exitCode==="") exitCode=m[1]; bodyLines.pop(); continue; }
    break;
  }
  return {
    exitCode: exitCode,
    durationMs: durationMs,
    output: bodyLines.join(String.fromCharCode(10)).trim(),
    stdout: meta && meta.stdout,
    stderr: meta && meta.stderr
  };
}
function nCommandLineCount(txt){
  txt=String(txt==null?"":txt).trim();
  return txt ? txt.split(String.fromCharCode(10)).length : 0;
}
function nCommandSectionHtml(label, txt, cls){
  txt=String(txt==null?"":txt);
  if(!txt.trim()) return "";
  return '<div class="cmd-section '+cls+'"><div class="cmd-section-label">'+nEsc(label)+'</div><pre>'+nEsc(txt.trim())+'</pre></div>';
}
function nCommandResultHtml(txt, toolName, meta){
  var name=String(toolName||"").toLowerCase();
  if(name!=="bash" && name!=="powershell") return "";
  var parts=nCommandResultParts(txt, meta||{}), stdout=parts.stdout, stderr=parts.stderr;
  var hasSplit=(stdout!=null && String(stdout).trim()) || (stderr!=null && String(stderr).trim());
  var output=hasSplit?"":parts.output;
  var bodyCount=hasSplit ? (nCommandLineCount(stdout)+nCommandLineCount(stderr)) : nCommandLineCount(output);
  var summary="Command";
  if(parts.exitCode!=null && parts.exitCode!=="") summary+=" · exit "+parts.exitCode;
  if(parts.durationMs!=null && parts.durationMs!=="" && typeof nFmtDur==="function") summary+=" · "+nFmtDur(parts.durationMs);
  summary+=" · "+bodyCount+" output line"+(bodyCount===1?"":"s");
  var body=hasSplit
    ? (nCommandSectionHtml("stdout", stdout, "cmd-stdout")+nCommandSectionHtml("stderr", stderr, "cmd-stderr"))
    : nCommandSectionHtml("output", output || "(no output)", "cmd-output");
  var openAttr=(bodyCount>80 && String(parts.exitCode||"0")==="0")?"":" open";
  return '<details class="tres-det cmd-det"'+openAttr+'><summary>'+nEsc(summary)+'</summary>'+body+'</details>';
}
function nDiffStats(txt){
  var lines=String(txt==null?"":txt).split(String.fromCharCode(10));
  var files={}, add=0, del=0;
  function fkey(path){
    path=String(path||"");
    if(path.indexOf("a/")===0 || path.indexOf("b/")===0) path=path.slice(2);
    return path;
  }
  lines.forEach(function(line){
    if(line.indexOf("diff --git ")===0){
      var parts=line.split(" ");
      files[fkey(parts[3]||parts[2]||line)]=true;
    }
    else if(line.indexOf("+++ ")===0){ files[fkey(line.slice(4))]=true; }
    else if(line.indexOf("+")===0){ add++; }
    else if(line.indexOf("-")===0 && line.indexOf("--- ")!==0){ del++; }
  });
  var fileCount=Object.keys(files).filter(function(k){ return k && k!=="/dev/null"; }).length;
  return {lines:lines.length, files:fileCount, add:add, del:del};
}
function nLooksLikeDiff(txt){
  txt=String(txt==null?"":txt);
  return txt.indexOf("diff --git ")>=0 || txt.indexOf(String.fromCharCode(10)+"@@ ")>=0 ||
         txt.indexOf("--- ")===0 || txt.indexOf(String.fromCharCode(10)+"--- ")>=0;
}
function nDiffLineClass(line){
  if(line.indexOf("@@")===0) return "du-hunk";
  if(line.indexOf("diff --git ")===0 || line.indexOf("index ")===0 || line.indexOf("+++ ")===0 || line.indexOf("--- ")===0) return "du-file";
  if(line.indexOf("+")===0) return "du-add";
  if(line.indexOf("-")===0) return "du-del";
  return "du-line";
}
function nDiffResultHtml(txt){
  txt=String(txt==null?"":txt);
  var st=nDiffStats(txt), summary="Diff";
  if(st.files) summary+=" · "+st.files+" file"+(st.files>1?"s":"");
  summary+=" · +"+st.add+" -"+st.del+" · "+st.lines+" lines";
  var rows=txt.split(String.fromCharCode(10)).map(function(line){
    return '<span class="du-line '+nDiffLineClass(line)+'">'+nEsc(line || " ")+'</span>';
  }).join("");
  return '<details class="tres-det diff-det" open><summary>'+nEsc(summary)+'</summary><pre class="diff-unified">'+rows+'</pre></details>';
}
function nTryJson(txt){
  txt=String(txt==null?"":txt).trim();
  if(!txt || ("[{".indexOf(txt.charAt(0))<0)) return null;
  try{ return JSON.parse(txt); }catch(e){ return null; }
}
function nJsonResultSummary(obj, toolName){
  var label=toolName?("JSON · "+toolName):"JSON result";
  if(Array.isArray(obj)) return label+" · "+obj.length+" items";
  if(obj && typeof obj==="object"){
    var n=0; Object.keys(obj).forEach(function(){ n++; });
    if(obj.isError || obj.error) label+=" · error";
    else if(Array.isArray(obj.content)) label+=" · "+obj.content.length+" content";
    else if(Array.isArray(obj.contents)) label+=" · "+obj.contents.length+" resource";
    else label+=" · "+n+" fields";
  }
  return label;
}
function nJsonResultPreview(obj){
  var items=[];
  function addText(t){ t=String(t||"").trim(); if(t) items.push(t.slice(0,240)); }
  if(Array.isArray(obj)){ obj.slice(0,3).forEach(function(x){ addText(typeof x==="string"?x:JSON.stringify(x)); }); }
  else if(obj && typeof obj==="object"){
    var arr=Array.isArray(obj.content)?obj.content:(Array.isArray(obj.contents)?obj.contents:[]);
    arr.slice(0,3).forEach(function(x){ addText((x&&x.text) || (x&&x.uri) || (x&&x.name) || JSON.stringify(x)); });
    if(!items.length && obj.error) addText(obj.error);
  }
  if(!items.length) return "";
  return '<div class="json-preview">'+items.map(function(t){ return '<div>'+nEsc(t)+'</div>'; }).join("")+'</div>';
}
function nJsonResultHtml(txt, toolName){
  var obj=nTryJson(txt);
  if(obj==null) return "";
  var pretty;
  try{ pretty=JSON.stringify(obj,null,2); }catch(e){ pretty=txt; }
  var summary=nJsonResultSummary(obj, toolName);
  return '<details class="tres-det json-det" open><summary>'+nEsc(summary)+'</summary>'+nJsonResultPreview(obj)+'<pre class="json-result">'+nEsc(pretty)+'</pre></details>';
}
function nToolResultMarkup(toolId, txt, toolName, meta){
  if(toolId==="turn-diff" || nLooksLikeDiff(txt)) return nDiffResultHtml(txt);
  var json=nJsonResultHtml(txt, toolName);
  return json || nCommandResultHtml(txt, toolName, meta) || nToolResultHtml(txt);
}
function nFindToolResultHost(st, tuid){
  var root=st.turnCard||st.root, nodes=root.querySelectorAll('.tool-entry,.nmsg.tool');
  for(var i=0;i<nodes.length;i++){ if(nodes[i].dataset && nodes[i].dataset.tuid===String(tuid||"")) return nodes[i]; }
  return null;
}
function nFindStandaloneResultHost(st, tuid){
  if(!tuid) return null;
  var root=st.turnCard||st.root, nodes=root.querySelectorAll('.nmsg.result[data-tuid]');
  for(var i=nodes.length-1;i>=0;i--){ if(nodes[i].dataset && nodes[i].dataset.tuid===String(tuid)) return nodes[i]; }
  return null;
}
function nRenderToolResult(st, tuid, txt, meta){
  var tu=nFindToolResultHost(st, tuid);
  var toolName=tu&&tu.dataset?tu.dataset.tname:"";
  var html=nToolResultMarkup(tuid, txt, toolName, meta);
  if(tu){
    var r=tu.querySelector('.tres'); if(r){ r.innerHTML=html; }
    return;
  }
  var old=nFindStandaloneResultHost(st, tuid);
  if(old){ old.innerHTML=html; return; }
  var d=document.createElement("div"); d.className="nmsg result";
  if(tuid) d.dataset.tuid=String(tuid);
  d.innerHTML=html; (st.turnCard||st.root).appendChild(d); nScrollBottom();
}
