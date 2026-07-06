"use strict";

self.addEventListener("notificationclick", function(event) {
  event.notification.close();
  var data = event.notification.data || {};
  var sid = data.sid || "";
  var url = data.url || "/";

  event.waitUntil(self.clients.matchAll({
    type: "window",
    includeUncontrolled: true
  }).then(function(clientList) {
    for (var i = 0; i < clientList.length; i += 1) {
      var client = clientList[i];
      if (client.url.indexOf(self.location.origin) === 0) {
        if (sid) {
          client.postMessage({type: "open-session", sid: sid});
        }
        return client.focus();
      }
    }
    return self.clients.openWindow(url);
  }));
});
