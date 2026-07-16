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
function nDiffCleanPath(path){
  path=String(path||"").trim();
  if(path.indexOf("\"")===0 && path.lastIndexOf("\"")===path.length-1) path=path.slice(1,-1);
  if(path.indexOf("a/")===0 || path.indexOf("b/")===0) path=path.slice(2);
  return path;
}
function nDiffGitPath(line){
  var parts=String(line||"").split(" ");
  return nDiffCleanPath(parts[3]||parts[2]||"patch") || "patch";
}
function nDiffSetSectionPath(sec, path, prefer){
  path=nDiffCleanPath(path);
  if(!path || path==="/dev/null") return;
  if(prefer || !sec.path || sec.path==="patch") sec.path=path;
}
function nDiffFileSections(txt){
  var lines=String(txt==null?"":txt).split(String.fromCharCode(10));
  var sections=[], cur=null;
  function start(path){
    if(cur && cur.lines.length) sections.push(cur);
    cur={path:path||"patch", lines:[], add:0, del:0, status:""};
  }
  lines.forEach(function(line){
    if(line.indexOf("diff --git ")===0) start(nDiffGitPath(line));
    if(!cur) start("patch");
    cur.lines.push(line);
    if(line.indexOf("+++ ")===0) nDiffSetSectionPath(cur, line.slice(4), true);
    else if(line.indexOf("--- ")===0) nDiffSetSectionPath(cur, line.slice(4), false);
    else if(line.indexOf("new file mode")===0) cur.status="added";
    else if(line.indexOf("deleted file mode")===0) cur.status="deleted";
    else if(line.indexOf("rename from ")===0 || line.indexOf("rename to ")===0) cur.status="renamed";
    else if(line.indexOf("Binary files ")===0) cur.status="binary";
    if(line.indexOf("+")===0 && line.indexOf("+++ ")!==0) cur.add++;
    else if(line.indexOf("-")===0 && line.indexOf("--- ")!==0) cur.del++;
  });
  if(cur && cur.lines.length) sections.push(cur);
  return sections;
}
function nDiffStats(txt){
  var lines=String(txt==null?"":txt).split(String.fromCharCode(10));
  var seen={}, fileList=[], add=0, del=0;
  nDiffFileSections(txt).forEach(function(sec){
    add+=sec.add; del+=sec.del;
    if(sec.path && !seen[sec.path]){ seen[sec.path]=true; fileList.push(sec.path); }
  });
  return {lines:lines.length, files:fileList.length, add:add, del:del, fileList:fileList};
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
function nDiffFileLabel(item){
  if(typeof item==="string") return {path:item, add:null, del:null, status:""};
  return {path:(item&&item.path)||"patch", add:item&&item.add, del:item&&item.del, status:(item&&item.status)||""};
}
function nDiffFileListHtml(files){
  files=Array.isArray(files)?files:[];
  if(!files.length) return "";
  var max=8, shown=files.slice(0,max).map(function(item){
    var f=nDiffFileLabel(item), stats=(f.add!=null||f.del!=null)?'<span class="diff-file-chip-stat">+'+(f.add||0)+' -'+(f.del||0)+'</span>':"";
    var status=f.status?'<span class="diff-file-chip-status">'+nEsc(f.status)+'</span>':"";
    return '<span class="diff-file-chip">'+nEsc(f.path)+stats+status+'</span>';
  }).join("");
  var more=files.length>max?'<span class="diff-file-more">+'+(files.length-max)+' more</span>':"";
  return '<div class="diff-file-list">'+shown+more+'</div>';
}
function nDiffPatchSummaryHtml(st, sections){
  var largest=null;
  sections.forEach(function(sec){ if(!largest || (sec.add+sec.del)>(largest.add+largest.del)) largest=sec; });
  var bits=['<span>'+st.files+' file'+(st.files===1?'':'s')+'</span>','<span>+'+st.add+' -'+st.del+'</span>','<span>'+st.lines+' lines</span>'];
  if(largest && st.files>1) bits.push('<span>largest: '+nEsc(largest.path)+' +'+largest.add+' -'+largest.del+'</span>');
  return '<div class="diff-patch-summary">'+bits.join('')+'</div>';
}
function nDiffRowsHtml(lines){
  return lines.map(function(line){
    return '<span class="du-line '+nDiffLineClass(line)+'">'+nEsc(line || " ")+'</span>';
  }).join("");
}
function nDiffBodyHtml(sections, isLarge){
  if(sections.length<=1){
    var only=sections[0]||{lines:[""]};
    return '<pre class="diff-unified">'+nDiffRowsHtml(only.lines)+'</pre>';
  }
  return '<div class="diff-file-sections">'+sections.map(function(sec){
    var stat='+'+sec.add+' -'+sec.del+(sec.status?' | '+sec.status:'');
    var openAttr=(!isLarge && sec.lines.length<=120)?' open':'';
    return '<details class="diff-file-section"'+openAttr+'><summary><span class="diff-file-title">'+nEsc(sec.path||"patch")+'</span><span class="diff-file-stat">'+nEsc(stat)+'</span></summary><pre class="diff-unified">'+nDiffRowsHtml(sec.lines)+'</pre></details>';
  }).join("")+'</div>';
}
function nDiffResultHtml(txt){
  txt=String(txt==null?"":txt);
  var sections=nDiffFileSections(txt), st=nDiffStats(txt), summary="Diff";
  if(st.files) summary+=" | "+st.files+" file"+(st.files>1?"s":"");
  summary+=" | +"+st.add+" -"+st.del+" | "+st.lines+" lines";
  var isLarge=st.lines>220 || st.files>8;
  return '<details class="tres-det diff-det'+(isLarge?' diff-large':'')+'"'+(isLarge?'':' open')+'><summary>'+nEsc(summary)+'</summary>'+nDiffPatchSummaryHtml(st, sections)+nDiffFileListHtml(sections)+'<div class="diff-body">'+nDiffBodyHtml(sections, isLarge)+'</div></details>';
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
