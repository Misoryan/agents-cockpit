"use strict";
/* ---- main view switching ---- */
function setMainView(view){
  var id=view==="usage"?"usageview":view==="native"?"nativestage":"landing";
  ["landing","usageview","nativestage"].forEach(function(x){ $(x).classList.toggle("active", x===id); });
  if(id==="usageview") refreshCC();
  if(id==="landing") renderSummary();
}

/* ---- structured agent session ---- */
var currentSid=null;
var nativeStages={}, nativeWs={}, nativeReconnectTimers={}, nativeReconnectState={}, nativePollTimers={}, nativePollBusy={};
var lmDir="", lmTitle="", lmBackend="codex_native", lmYolo=true;
var lmCodexModel="", lmCodexSearch="", lmCodexSandbox="", lmCodexApproval="", lmCodexReasoning="", lmCodexSummary="", lmCodexServiceTier="", lmCodexWritableRoots="", lmCodexOptionsKey="";
/* Preferences: cookie first, with localStorage fallback migrated into cookies. */
(function(){
  var b = acPrefGetRaw("acBackend", "acBackend");
  lmBackend = b.val || "codex_native";
  if(b.src === "none") acSetCookie("acBackend", lmBackend, 3650);
  var y = acPrefGetRaw("acYolo", "acYolo");
  lmYolo = (y.val === "") ? true : (y.val !== "0");
  if(y.src === "none") acSetCookie("acYolo", lmYolo ? "1" : "0", 3650);
  lmCodexModel = acPrefGetRaw("acCodexModel", "acCodexModel").val || "";
  lmCodexSearch = acPrefGetRaw("acCodexSearch", "acCodexSearch").val || "";
  lmCodexSandbox = acPrefGetRaw("acCodexSandbox", "acCodexSandbox").val || "";
  lmCodexApproval = acPrefGetRaw("acCodexApproval", "acCodexApproval").val || "";
  lmCodexReasoning = acPrefGetRaw("acCodexReasoning", "acCodexReasoning").val || "";
  lmCodexSummary = acPrefGetRaw("acCodexSummary", "acCodexSummary").val || "";
  lmCodexServiceTier = acPrefGetRaw("acCodexServiceTier", "acCodexServiceTier").val || "";
  lmCodexWritableRoots = acPrefGetRaw("acCodexWritableRoots", "acCodexWritableRoots").val || "";
})();
