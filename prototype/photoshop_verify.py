"""Optional real-host verification of isolated upstream fixture copies only.

Run using a Python with pywin32, AFTER prototype.verify_samples. Requires an
already-running Photoshop; never launches/quits Photoshop or saves source PSDs.
"""
import json
import re
from datetime import datetime
from pathlib import Path

SCRIPT = r'''
(function () {
    var base = __BASE__;
    var renderDir = __RENDERS__;
    var names = ["smart-object-slice.psd", "smart-object-slice.psb", "smart-object-v8.psd", "placedLayer.psd"];
    var originalActive = app.documents.length ? app.activeDocument : null;
    var oldDialogs = app.displayDialogs;
    var owned = [];
    var results = [];
    function layers(node) {
        var out = [];
        for (var i = 0; i < node.layers.length; i++) {
            var l = node.layers[i];
            out.push([l.name, l.typename, String(l.kind), l.visible, l.opacity, String(l.blendMode), String(l.bounds)]);
            if (l.typename === "LayerSet") { out.push(layers(l)); }
        }
        return out;
    }
    function inspect(doc, depth, enterChildren) {
        if (depth > 8) { throw new Error("Verification nesting limit"); }
        app.activeDocument = doc;
        var xmp = new XMPMeta(doc.xmpMetadata.rawData);
        results.push([depth, xmp.doesPropertyExist(XMPConst.NS_PHOTOSHOP, "DocumentAncestors"), layers(doc)].toSource());
        if (!enterChildren) { return; }
        function visit(node) {
            for (var i = 0; i < node.layers.length; i++) {
                var layer = node.layers[i];
                if (layer.typename === "LayerSet") { visit(layer); continue; }
                if (layer.kind !== LayerKind.SMARTOBJECT) { continue; }
                app.activeDocument = doc;
                doc.activeLayer = layer;
                var before = app.documents.length;
                executeAction(stringIDToTypeID("placedLayerEditContents"), new ActionDescriptor(), DialogModes.NO);
                if (app.documents.length !== before + 1 || app.activeDocument === doc) {
                    throw new Error("Verification did not open a new embedded document");
                }
                var child = app.activeDocument;
                owned.push(child);
                inspect(child, depth + 1, true);
                child.close(SaveOptions.DONOTSAVECHANGES);
                owned.pop();
                app.activeDocument = doc;
            }
        }
        visit(doc);
    }
    try {
        app.displayDialogs = DialogModes.NO;
        if (ExternalObject.AdobeXMPScript === undefined) { ExternalObject.AdobeXMPScript = new ExternalObject("lib:AdobeXMPScript"); }
        for (var n = 0; n < names.length; n++) {
            for (var pass = 0; pass < 2; pass++) {
                var folder = pass === 0 ? "injected" : "cleaned";
                var file = new File(base + "/" + folder + "/" + names[n]);
                for (var d = 0; d < app.documents.length; d++) {
                    try {
                        if (app.documents[d].fullName.fsName.toLowerCase() === file.fsName.toLowerCase()) {
                            throw new Error("Verification fixture already open; refusing to touch it");
                        }
                    } catch (err) { if (String(err).indexOf("refusing") >= 0) { throw err; } }
                }
                var doc = app.open(file);
                owned.push(doc);
                results.push("FILE:" + folder + "/" + names[n]);
                // Save a PNG copy, not Save for Web: fixture slices would split the export.
                doc.saveAs(new File(renderDir + "/" + folder + "-" + names[n] + ".png"),
                           new PNGSaveOptions(), true, Extension.LOWERCASE);
                // Only the known PSD/PSB embedded fixtures are opened recursively.
                inspect(doc, 0, names[n].indexOf("smart-object-slice") === 0);
                doc.close(SaveOptions.DONOTSAVECHANGES);
                owned.pop();
            }
        }
        return results.join("\n");
    } finally {
        for (var j = owned.length - 1; j >= 0; j--) { try { owned[j].close(SaveOptions.DONOTSAVECHANGES); } catch (e) {} }
        app.displayDialogs = oldDialogs;
        if (originalActive !== null) { try { app.activeDocument = originalActive; } catch (e) {} }
    }
})();
'''


def validate_report(base, report):
    from PIL import Image
    records = {}
    current = None
    for line in report["inspection"]:
        if line.startswith("FILE:"):
            current = line[5:]
            records[current] = []
        else:
            records[current].append(line)
    checks = []
    renders = Path(report.get("render_dir", base / "renders"))
    for name in ("smart-object-slice.psd", "smart-object-slice.psb", "smart-object-v8.psd", "placedLayer.psd"):
        before, after = records["injected/" + name], records["cleaned/" + name]
        ancestors_ok = (bool(before) and len(before) == len(after)
                        and all(re.match(r"^\[\d+, true,", line) for line in before)
                        and all(re.match(r"^\[\d+, false,", line) for line in after))
        normalized = lambda lines: [re.sub(r"^(\[\d+), (true|false),", r"\1,", line) for line in lines]
        with Image.open(renders / ("injected-" + name + ".png")) as image:
            original = image.convert("RGBA")
        with Image.open(renders / ("cleaned-" + name + ".png")) as image:
            cleaned = image.convert("RGBA")
        checks.append({"sample": name, "ancestors_removed": bool(ancestors_ok),
                       "layers_unchanged": normalized(before) == normalized(after),
                       "render_pixels_equal": original.size == cleaned.size and original.tobytes() == cleaned.tobytes()})
    return checks


def main():
    import pythoncom
    import win32com.client
    base = Path(".prototype-data").resolve()
    for name in ("injected", "cleaned"):
        if not (base / name / "smart-object-slice.psd").is_file():
            raise RuntimeError("Run prototype.verify_samples first")
    render_dir = base / "renders" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    render_dir.mkdir(parents=True)
    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("Photoshop.Application")
        # Photoshop's IDispatch metadata may expose this method as a property.
        app._FlagAsMethod("DoJavaScript")
        version = str(app.Version)
        before_count = int(app.Documents.Count)
        script = SCRIPT.replace("__BASE__", json.dumps(base.as_posix())).replace("__RENDERS__", json.dumps(render_dir.as_posix()))
        result = str(app.DoJavaScript(script))
        after_count = int(app.Documents.Count)
        report = {"photoshop_version": version, "render_dir": str(render_dir), "before_documents": before_count,
                  "after_documents": after_count, "inspection": result.splitlines()}
        report["checks"] = validate_report(base, report)
        (base / "photoshop-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True, indent=2))
        if before_count != after_count:
            raise RuntimeError("Document count changed; inspect Photoshop before continuing")
        if not all(check[flag] for check in report["checks"]
                   for flag in ("ancestors_removed", "layers_unchanged", "render_pixels_equal")):
            raise RuntimeError("Photoshop compatibility verification failed; inspect photoshop-report.json")
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
