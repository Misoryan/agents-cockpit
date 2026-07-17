var _luBusy=false;
var _ICONS={
"menu":"<path d=\"M4 6h16M4 12h16M4 18h16\"/>",
"plus":"<path d=\"M5 12h14M12 5v14\"/>",
"panel-left-close":"<rect width=\"18\" height=\"18\" x=\"3\" y=\"3\" rx=\"2\"/><path d=\"M9 8v8\"/><path d=\"m15 9-3 3 3 3\"/>",
"square-pen":"<path d=\"M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7\"/><path d=\"M18.5 3.5a2.12 2.12 0 0 1 3 3L12 16l-4 1 1-4Z\"/>",
"settings":"<path d=\"M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z\"/><circle cx=\"12\" cy=\"12\" r=\"3\"/>",
"arrow-left":"<path d=\"m12 19-7-7 7-7\"/><path d=\"M19 12H5\"/>",
"arrow-up":"<path d=\"m5 12 7-7 7 7\"/><path d=\"M12 19V5\"/>",
"arrow-down":"<path d=\"M12 5v14\"/><path d=\"m19 12-7 7-7-7\"/>",
"chevron-right":"<path d=\"m9 18 6-6-6-6\"/>",
"chevron-down":"<path d=\"m6 9 6 6 6-6\"/>",
"check":"<path d=\"M20 6 9 17l-5-5\"/>",
"square":"<rect x=\"3\" y=\"3\" width=\"18\" height=\"18\" rx=\"2\"/>",
"play":"<polygon points=\"6 3 20 12 6 21 6 3\"/>",
"folder":"<path d=\"M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z\"/>",
"folder-open":"<path d=\"M4 20h7a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z\"/><path d=\"m14 17 6-3-6-3\"/>",
"clipboard-list":"<rect width=\"8\" height=\"4\" x=\"8\" y=\"2\" rx=\"1\"/><path d=\"M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2\"/><path d=\"M12 11h4\"/><path d=\"M12 16h4\"/><path d=\"M8 11h.01\"/><path d=\"M8 16h.01\"/>",
"list-checks":"<path d=\"m3 17 2 2 4-4\"/><path d=\"m3 7 2 2 4-4\"/><path d=\"M13 6h8\"/><path d=\"M13 12h8\"/><path d=\"M13 18h8\"/>",
"refresh-cw":"<path d=\"M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8\"/><path d=\"M21 3v5h-5\"/><path d=\"M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16\"/><path d=\"M3 21v-5h5\"/>",
"alert":"<path d=\"m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z\"/><path d=\"M12 9v4\"/><path d=\"M12 17h.01\"/>",
"circle-check":"<path d=\"M22 11.08V12a10 10 0 1 1-5.93-9.14\"/><path d=\"m9 11 3 3L22 4\"/>",
"sparkles":"<path d=\"M9.94 14.34A2 2 0 0 0 8.5 13.06l-6.13-1.58a.5.5 0 0 1 0-.96L8.5 8.94A2 2 0 0 0 9.94 7.5l1.58-6.13a.5.5 0 0 1 .96 0l1.58 6.13A2 2 0 0 0 15.5 8.94l6.13 1.58a.5.5 0 0 1 0 .96L15.5 13.06a2 2 0 0 0-1.44 1.44l-1.58 6.13a.5.5 0 0 1-.96 0z\"/><path d=\"M18 5v4\"/><path d=\"M16 7h4\"/>",
"bell":"<path d=\"M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9\"/><path d=\"M10.3 21a1.94 1.94 0 0 0 3.4 0\"/>",
"scissors":"<circle cx=\"6\" cy=\"6\" r=\"3\"/><path d=\"M8.12 8.12 12 12\"/><path d=\"M20 4 8.12 8.12\"/><circle cx=\"6\" cy=\"18\" r=\"3\"/><path d=\"M8.12 15.88 12 12\"/><path d=\"M20 20 8.12 15.88\"/>",
"ban":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m4.9 4.9 14.2 14.2\"/>",
"pause":"<rect x=\"6\" y=\"4\" width=\"4\" height=\"16\" rx=\"1\"/><rect x=\"14\" y=\"4\" width=\"4\" height=\"16\" rx=\"1\"/>",
"wrench":"<path d=\"M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z\"/>",
"message-circle":"<path d=\"M7.9 20A9 9 0 1 0 4 16.1L2 22Z\"/>",
"circle-dashed":"<path d=\"M10.1 2.18a10 10 0 0 1 11.7 7.64\"/><path d=\"M21.9 14.16A10 10 0 0 1 2.34 15.1\"/><path d=\"M5.5 19.5 4 22\"/><path d=\"M2 12a10 10 0 0 1 3.18-7.3\"/>",
"circle":"<circle cx=\"12\" cy=\"12\" r=\"10\"/>",
"pencil":"<path d=\"M21.17 6.81a1 1 0 0 0-3.98-3.98L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z\"/><path d=\"m15 5 4 4\"/>",
"help-circle":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3\"/><path d=\"M12 17h.01\"/>",
"receipt":"<path d=\"M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z\"/><path d=\"M8 7h8\"/><path d=\"M8 11h8\"/><path d=\"M8 15h5\"/>",
"search":"<circle cx=\"11\" cy=\"11\" r=\"8\"/><path d=\"m21 21-4.3-4.3\"/>",
"terminal":"<path d=\"m4 17 6-6-6-6\"/><path d=\"M12 19h8\"/>",
"book-open":"<path d=\"M12 7v14\"/><path d=\"M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z\"/>",
"file-text":"<path d=\"M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z\"/><path d=\"M14 2v4a2 2 0 0 0 2 2h4\"/><path d=\"M16 13H8\"/><path d=\"M16 17H8\"/>",
"globe":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20\"/><path d=\"M2 12h20\"/>",
"hourglass":"<path d=\"M5 22h14\"/><path d=\"M5 2h14\"/><path d=\"M17 22v-4.17a2 2 0 0 0-.59-1.41L12 12l-4.42 4.42a2 2 0 0 0-.58 1.41V22\"/><path d=\"M7 2v4.17a2 2 0 0 0 .59 1.41L12 12l4.42-4.42a2 2 0 0 0 .58-1.41V2\"/>",
"lock":"<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>",
"archive":"<rect width=\"20\" height=\"5\" x=\"2\" y=\"3\" rx=\"1\"/><path d=\"M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8\"/><path d=\"M10 12h4\"/>",
"circle-alert":"<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"M12 8v4\"/><path d=\"M12 16h.01\"/>",
"image-plus":"<path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7'/><line x1='16' x2='22' y1='5' y2='5'/><line x1='19' x2='19' y1='2' y2='8'/><circle cx='9' cy='9' r='2'/><path d='m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21'/>",
"bar-chart-3":"<path d='M3 3v18h18'/><path d='M18 17V9'/><path d='M13 17V5'/><path d='M8 17v-3'/>",
"git-branch":"<line x1='6' x2='6' y1='3' y2='15'/><circle cx='18' cy='6' r='3'/><circle cx='6' cy='18' r='3'/><path d='M18 9a9 9 0 0 1-9 9'/>",
"loader":"<line x1='12' x2='12' y1='2' y2='6'/><line x1='12' x2='12' y1='18' y2='22'/><line x1='4.93' x2='7.76' y1='4.93' y2='7.76'/><line x1='16.24' x2='19.07' y1='16.24' y2='19.07'/><line x1='2' x2='6' y1='12' y2='12'/><line x1='18' x2='22' y1='12' y2='12'/><line x1='4.93' x2='7.76' y1='19.07' y2='16.24'/><line x1='16.24' x2='19.07' y1='7.76' y2='4.93'/>"
};
function _I(n,cls){var p=_ICONS[n];return p?"<svg class=\""+(cls||"ic")+"\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.75\" stroke-linecap=\"round\" stroke-linejoin=\"round\">"+p+"</svg>":"";}
function renderIcs(root){(root||document).querySelectorAll("[data-lucide]").forEach(function(el){var n=el.getAttribute("data-lucide"),p=_ICONS[n];if(p==null)return;var c=el.getAttribute("class")||"";el.outerHTML="<svg class=\""+c+"\" viewBox=\"0 0 24 24\" fill=\"none\" stroke=\"currentColor\" stroke-width=\"1.75\" stroke-linecap=\"round\" stroke-linejoin=\"round\">"+p+"</svg>";});}
var _icBusy=false;
function _icRefresh(){if(_icBusy)return;_icBusy=true;try{renderIcs();}catch(e){}setTimeout(function(){_icBusy=false;},50);}
_icRefresh();
if('MutationObserver' in window){
  new MutationObserver(function(){_icRefresh();}).observe(document.body,{childList:true,subtree:true});
}
