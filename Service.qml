import QtQuick
import Quickshell
import Quickshell.Io

Scope {
  id: root
  property var shell: null
  property var manifest: null
  property bool registered: false
  readonly property string sourceDir: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, ""))
  function open() {
    Quickshell.execDetached(["python", sourceDir + "/reader.py"])
  }
  IpcHandler {
    target: "dispatch"
    function open(): void { root.open() }
    function status(): string { return root.sourceDir }
  }
  Component.onCompleted: {
    if (!registered) {
      registered = true
      Quickshell.execDetached(["python", sourceDir + "/integration.py", "install"])
    }
  }
  Component.onDestruction: {
    if (registered)
      Quickshell.execDetached(["python", sourceDir + "/integration.py", "remove"])
  }
}
