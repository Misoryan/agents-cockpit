"use strict";
/* ---- init ---- */
(function(){ if("serviceWorker" in navigator){ navigator.serviceWorker.getRegistrations().then(function(rs){ rs.forEach(function(r){ r.unregister(); }); }).catch(function(){}); } })();
renderBackend("lm-backend"); renderYolo("lm-yolo","lm-yolo-sw"); renderYolo("set-yolo","set-yolo-sw");
if(typeof nativeRenderViewToggle==="function") nativeRenderViewToggle();
setMainView("landing");
renderSessionTabs();
loadSidebarData(); pollSessionSignals(); refreshCC();
setInterval(pollSessionSignals, 4000);
setInterval(loadSidebarData, 20000);
setInterval(refreshCC, 30000);
