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
function nMcpSlashArg(value){
  value=String(value==null?"":value);
  return '"'+value.replace(/\\/g,"\\\\").replace(/"/g,'\\"')+'"';
}
function nMcpActionButton(command, label){
  if(!command) return "";
  return '<button type="button" class="mcp-action" data-mcp-command="'+nEscAttr(command)+'">'+nEsc(label||"Open")+'</button>';
}
function nMcpCountLabel(count, one, many){
  count=Number(count)||0;
  return count+" "+(count===1?one:many);
}
function nMcpResourceRows(server, resources){
  resources=Array.isArray(resources)?resources:[];
  if(!resources.length) return '<div class="mcp-empty">No resources</div>';
  var max=20;
  var rows=resources.slice(0,max).map(function(res){
    res=res||{};
    var name=res.name||res.title||res.uri||"resource", uri=res.uri||"", desc=res.description||"", mime=res.mimeType||"";
    var meta=[mime, desc].filter(Boolean).join(" 路 ");
    var cmd=uri?('/mcp-resource '+nMcpSlashArg(server)+" "+nMcpSlashArg(uri)):"";
    return '<div class="mcp-row"><div class="mcp-row-main"><b>'+nEsc(name)+'</b><span>'+nEsc(uri)+'</span>'+(meta?'<small>'+nEsc(meta)+'</small>':'')+'</div>'+nMcpActionButton(cmd,"Read")+'</div>';
  }).join("");
  if(resources.length>max) rows+='<div class="mcp-more">+'+(resources.length-max)+' more resources</div>';
  return rows;
}
function nMcpTemplateRows(templates){
  templates=Array.isArray(templates)?templates:[];
  if(!templates.length) return '<div class="mcp-empty">No resource templates</div>';
  var max=12;
  var rows=templates.slice(0,max).map(function(tpl){
    tpl=tpl||{};
    var name=tpl.name||tpl.title||tpl.uriTemplate||"template", uri=tpl.uriTemplate||"", meta=[tpl.mimeType||"", tpl.description||""].filter(Boolean).join(" 路 ");
    return '<div class="mcp-row passive"><div class="mcp-row-main"><b>'+nEsc(name)+'</b><span>'+nEsc(uri)+'</span>'+(meta?'<small>'+nEsc(meta)+'</small>':'')+'</div></div>';
  }).join("");
  if(templates.length>max) rows+='<div class="mcp-more">+'+(templates.length-max)+' more templates</div>';
  return rows;
}
function nMcpToolRows(tools){
  tools=Array.isArray(tools)?tools:[];
  if(!tools.length) return '<div class="mcp-empty">No tools</div>';
  var max=16;
  var rows=tools.slice(0,max).map(function(tool){
    tool=tool||{};
    return '<div class="mcp-row passive"><div class="mcp-row-main"><b>'+nEsc(tool.name||"tool")+'</b>'+(tool.description?'<span>'+nEsc(tool.description)+'</span>':'')+'</div></div>';
  }).join("");
  if(tools.length>max) rows+='<div class="mcp-more">+'+(tools.length-max)+' more tools</div>';
  return rows;
}
function nMcpRawDetails(obj){
  var pretty;
  try{ pretty=JSON.stringify(obj,null,2); }catch(e){ pretty=""; }
  return pretty?'<details class="mcp-raw"><summary>Raw JSON</summary><pre class="json-result">'+nEsc(pretty)+'</pre></details>':"";
}
function nMcpServerCard(server){
  server=server||{};
  var name=server.name||"MCP server", auth=server.authStatus||"unknown";
  var tools=server.toolList||[], resources=server.resourceList||[], templates=server.resourceTemplateList||[];
  var toolCount=server.tools!=null?server.tools:tools.length;
  var resCount=server.resources!=null?server.resources:resources.length;
  var tplCount=server.resourceTemplates!=null?server.resourceTemplates:templates.length;
  var browse=nMcpActionButton('/mcp-resources '+nMcpSlashArg(name), "Browse");
  var body="";
  if(resources.length){ body+='<div class="mcp-section"><h4>Resources</h4>'+nMcpResourceRows(name, resources)+'</div>'; }
  if(templates.length){ body+='<div class="mcp-section"><h4>Templates</h4>'+nMcpTemplateRows(templates)+'</div>'; }
  if(tools.length){ body+='<div class="mcp-section"><h4>Tools</h4>'+nMcpToolRows(tools)+'</div>'; }
  return '<div class="mcp-server-card"><div class="mcp-card-head"><div><b>'+nEsc(name)+'</b><span>'+nEsc(auth)+'</span></div><div class="mcp-counts"><span>'+nMcpCountLabel(toolCount,"tool","tools")+'</span><span>'+nMcpCountLabel(resCount,"resource","resources")+'</span><span>'+nMcpCountLabel(tplCount,"template","templates")+'</span></div>'+browse+'</div>'+body+'</div>';
}
function nMcpStatusResultHtml(obj, toolName){
  var name=String(toolName||"").toLowerCase();
  var isStatus=name==="mcpserverstatus.list" || (obj && Array.isArray(obj.servers));
  var isResources=name==="mcpserverstatus.resources" || (obj && obj.server && (Array.isArray(obj.resources)||Array.isArray(obj.resourceTemplates)));
  if(!isStatus && !isResources) return "";
  if(isResources){
    var server=obj.server||"MCP server", resources=obj.resources||[], templates=obj.resourceTemplates||[], tools=obj.tools||[];
    var summary="MCP Resources | "+server+" | "+nMcpCountLabel(resources.length,"resource","resources")+" | "+nMcpCountLabel(templates.length,"template","templates")+" | "+nMcpCountLabel(tools.length,"tool","tools");
    return '<details class="tres-det mcp-det" open><summary>'+nEsc(summary)+'</summary><div class="mcp-resource-card"><div class="mcp-card-head"><div><b>'+nEsc(server)+'</b><span>'+nEsc(obj.authStatus||"unknown")+'</span></div></div><div class="mcp-section"><h4>Resources</h4>'+nMcpResourceRows(server, resources)+'</div><div class="mcp-section"><h4>Resource templates</h4>'+nMcpTemplateRows(templates)+'</div><div class="mcp-section"><h4>Tools</h4>'+nMcpToolRows(tools)+'</div>'+nMcpRawDetails(obj)+'</div></details>';
  }
  var servers=Array.isArray(obj.servers)?obj.servers:[];
  var sum="MCP Status | "+nMcpCountLabel(servers.length,"server","servers");
  if(obj.nextCursor) sum+=" | more pages";
  var body=servers.length?servers.map(nMcpServerCard).join(""):'<div class="mcp-empty">No MCP servers returned</div>';
  return '<details class="tres-det mcp-det" open><summary>'+nEsc(sum)+'</summary><div class="mcp-status-card">'+body+nMcpRawDetails(obj)+'</div></details>';
}
function nCodexSkillRows(skills){
  skills=Array.isArray(skills)?skills:[];
  if(!skills.length) return '<div class="mcp-empty">No skills</div>';
  var max=28;
  var rows=skills.slice(0,max).map(function(skill){
    skill=skill||{};
    var name=skill.displayName||skill.name||"skill";
    var desc=skill.shortDescription||skill.description||"";
    var meta=[skill.name&&skill.displayName?skill.name:"", skill.scope||"", skill.enabled===false?"disabled":"enabled"].filter(Boolean).join(" | ");
    return '<div class="mcp-row passive"><div class="mcp-row-main"><b>'+nEsc(name)+'</b>'+(meta?'<span>'+nEsc(meta)+'</span>':'')+(desc?'<small>'+nEsc(desc)+'</small>':'')+'</div></div>';
  }).join("");
  if(skills.length>max) rows+='<div class="mcp-more">+'+(skills.length-max)+' more skills</div>';
  return rows;
}
function nCodexSkillsResultHtml(obj){
  var roots=Array.isArray(obj&&obj.roots)?obj.roots:[], total=Number(obj&&obj.total)||0;
  var summary="Codex Skills | "+total+" total | "+(Number(obj&&obj.enabled)||0)+" enabled";
  var body=roots.length?roots.map(function(root){
    root=root||{};
    return '<div class="mcp-server-card"><div class="mcp-card-head"><div><b>'+nEsc(root.cwd||"Workspace")+'</b><span>'+nEsc((root.skills||[]).length+" shown")+'</span></div></div><div class="mcp-section"><h4>Skills</h4>'+nCodexSkillRows(root.skills)+'</div></div>';
  }).join(""):'<div class="mcp-empty">No skills returned</div>';
  return '<details class="tres-det mcp-det" open><summary>'+nEsc(summary)+'</summary><div class="mcp-status-card codex-inventory-card">'+body+nMcpRawDetails(obj)+'</div></details>';
}
function nCodexPluginRows(plugins){
  plugins=Array.isArray(plugins)?plugins:[];
  if(!plugins.length) return '<div class="mcp-empty">No plugins</div>';
  var max=24;
  var rows=plugins.slice(0,max).map(function(plugin){
    plugin=plugin||{};
    var flags=[];
    if(plugin.version) flags.push(plugin.version);
    if(plugin.installed===true) flags.push("installed");
    if(plugin.enabled===true) flags.push("enabled");
    var meta=[plugin.id||"", flags.join(", ")].filter(Boolean).join(" | ");
    return '<div class="mcp-row passive"><div class="mcp-row-main"><b>'+nEsc(plugin.name||plugin.id||"plugin")+'</b>'+(meta?'<span>'+nEsc(meta)+'</span>':'')+(plugin.description?'<small>'+nEsc(plugin.description)+'</small>':'')+'</div></div>';
  }).join("");
  if(plugins.length>max) rows+='<div class="mcp-more">+'+(plugins.length-max)+' more plugins</div>';
  return rows;
}
function nCodexPluginsResultHtml(obj){
  var markets=Array.isArray(obj&&obj.marketplaces)?obj.marketplaces:[], total=Number(obj&&obj.total)||0;
  var summary="Codex Plugins | "+(obj&&obj.mode||"installed")+" | "+total+" listed";
  var body=markets.length?markets.map(function(market){
    market=market||{};
    return '<div class="mcp-server-card"><div class="mcp-card-head"><div><b>'+nEsc(market.name||market.id||"Marketplace")+'</b><span>'+nEsc((market.plugins||[]).length+" plugins")+'</span></div></div><div class="mcp-section"><h4>Plugins</h4>'+nCodexPluginRows(market.plugins)+'</div></div>';
  }).join(""):'<div class="mcp-empty">No plugins returned</div>';
  var errors=Array.isArray(obj&&obj.marketplaceLoadErrors)?obj.marketplaceLoadErrors:[];
  if(errors.length) body+='<div class="mcp-section"><h4>Load errors</h4>'+nCodexPluginRows(errors.map(function(err, idx){ return {name:"error "+(idx+1), description:String(err)}; }))+'</div>';
  return '<details class="tres-det mcp-det" open><summary>'+nEsc(summary)+'</summary><div class="mcp-status-card codex-inventory-card">'+body+nMcpRawDetails(obj)+'</div></details>';
}
function nCodexInventoryResultHtml(obj, toolName){
  var name=String(toolName||"").toLowerCase();
  if(name==="codex.skills" || (obj && Array.isArray(obj.roots) && obj.total!=null)) return nCodexSkillsResultHtml(obj||{});
  if(name==="codex.plugins" || (obj && Array.isArray(obj.marketplaces) && obj.mode)) return nCodexPluginsResultHtml(obj||{});
  return "";
}
function nCodexAccountStatusLine(account){
  account=account||{};
  if(account.signed_in){
    return [account.type||"signed in", account.plan_type||"", account.credential_source||"", account.email||""].filter(Boolean).join(" | ");
  }
  if(account.requires_openai_auth) return "login required";
  return "not signed in";
}
function nCodexAccountBlock(label, value){
  if(!value || (typeof value==="object" && !Object.keys(value).length)) return "";
  var pretty=typeof value==="string"?value:JSON.stringify(value,null,2);
  return '<div class="mcp-section"><h4>'+nEsc(label)+'</h4><pre class="json-result">'+nEsc(pretty)+'</pre></div>';
}
function nCodexAccountResultHtml(obj, toolName){
  var name=String(toolName||"").toLowerCase();
  if(name!=="codex.accountstatus" && !(obj && obj.account && (obj.rateLimits||obj.usage||obj.errors))) return "";
  obj=obj||{};
  var account=obj.account||{}, errors=Array.isArray(obj.errors)?obj.errors:[];
  var summary="Codex Account | "+nCodexAccountStatusLine(account);
  if(errors.length) summary+=" | "+errors.length+" warnings";
  var body='<div class="mcp-server-card"><div class="mcp-card-head"><div><b>Account</b><span>'+nEsc(nCodexAccountStatusLine(account))+'</span></div></div>';
  if(errors.length){
    body+='<div class="mcp-section"><h4>Warnings</h4>'+errors.map(function(err){
      err=err||{};
      return '<div class="mcp-row passive"><div class="mcp-row-main"><b>'+nEsc(err.method||"read")+'</b><small>'+nEsc(err.error||"request failed")+'</small></div></div>';
    }).join("")+'</div>';
  }
  body+=nCodexAccountBlock("Rate limits", obj.rateLimits);
  body+=nCodexAccountBlock("Usage", obj.usage);
  body+='</div>';
  return '<details class="tres-det mcp-det" open><summary>'+nEsc(summary)+'</summary><div class="mcp-status-card codex-account-card">'+body+nMcpRawDetails(obj)+'</div></details>';
}
function nJsonResultHtml(txt, toolName){
  var obj=nTryJson(txt);
  if(obj==null) return "";
  var mcp=nMcpStatusResultHtml(obj, toolName);
  if(mcp) return mcp;
  var codexInventory=nCodexInventoryResultHtml(obj, toolName);
  if(codexInventory) return codexInventory;
  var codexAccount=nCodexAccountResultHtml(obj, toolName);
  if(codexAccount) return codexAccount;
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
