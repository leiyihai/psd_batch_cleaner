"""Opt-in Photoshop acceptance of isolated copies of an acceptance report's results.

Requires an idle, already-running Photoshop with NO open documents. Normal cleaning
never uses this module. The helper does not open the large original design files.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any


def deepest_chain(blob: bytes, depth: int = 0) -> list[int]:
    from psd_tools import PSDImage
    from psd_tools.api.layers import SmartObjectLayer
    if depth >= 16:
        return []
    doc = PSDImage.open(io.BytesIO(blob))
    best: list[int] = []
    seen = set()

    def visit(node):
        nonlocal best
        for layer in node:
            if layer.is_group():
                visit(layer)
            elif isinstance(layer, SmartObjectLayer) and layer.smart_object.kind == "data":
                payload = layer.smart_object.data
                if payload[:6] not in (b"8BPS\0\1", b"8BPS\0\2"):
                    continue
                identifier = layer.smart_object.unique_id
                if identifier in seen:
                    continue
                seen.add(identifier)
                candidate = [layer.layer_id] + deepest_chain(payload, depth + 1)
                if len(candidate) > len(best):
                    best = candidate
    visit(doc)
    return best


SCRIPT = r'''
(function () {
    var input = __INPUT__, roundtrip = __ROUNDTRIP__, beforePng = __BEFORE__, afterPng = __AFTER__;
    var chain = __CHAIN__;
    if (app.documents.length !== 0) { throw new Error("Host acceptance requires an empty Photoshop session"); }
    var owned = [], oldDialogs = app.displayDialogs, failed = false;
    function encode(v) {
        if (v === null) { return "null"; }
        if (typeof v === "string") { return '"' + v.replace(/\\/g,"\\\\").replace(/"/g,'\\"').replace(/\r/g,"\\r").replace(/\n/g,"\\n").replace(/\t/g,"\\t") + '"'; }
        if (v instanceof Array) { var parts=[]; for(var i=0;i<v.length;i++){parts.push(encode(v[i]));} return "["+parts.join(",")+"]"; }
        return String(v);
    }
    function layers(node) {
        var out=[];
        for(var i=0;i<node.layers.length;i++) {
            var l=node.layers[i];
            out.push([l.name,l.typename,l.typename === "ArtLayer" ? String(l.kind) : "LayerSet",l.visible,l.opacity,String(l.blendMode),String(l.bounds)]);
            if(l.typename === "LayerSet") { out.push(layers(l)); }
        }
        return out;
    }
    function inspect(doc, depth) {
        app.activeDocument=doc;
        var xmp=new XMPMeta(doc.xmpMetadata.rawData);
        var result=[[depth, xmp.doesPropertyExist(XMPConst.NS_PHOTOSHOP,"DocumentAncestors"),layers(doc)]];
        if(depth < chain.length) {
            var previous=doc.activeLayer;
            var ref=new ActionReference();ref.putIdentifier(charIDToTypeID("Lyr "),chain[depth]);
            var selection=new ActionDescriptor();selection.putReference(charIDToTypeID("null"),ref);
            selection.putBoolean(charIDToTypeID("MkVs"),false);
            executeAction(charIDToTypeID("slct"),selection,DialogModes.NO);
            var layer=doc.activeLayer,visible=layer.visible;
            var count=app.documents.length;
            executeAction(stringIDToTypeID("placedLayerEditContents"),new ActionDescriptor(),DialogModes.NO);
            if(app.documents.length !== count+1 || app.activeDocument===doc) { throw new Error("Embedded document did not open independently"); }
            var child=app.activeDocument;owned.push(child);
            result=result.concat(inspect(child,depth+1));
            child.close(SaveOptions.DONOTSAVECHANGES);owned.pop();
            app.activeDocument=doc;layer.visible=visible;doc.activeLayer=previous;
        }
        return result;
    }
    function png(doc,file) { app.activeDocument=doc;doc.saveAs(new File(file),new PNGSaveOptions(),true,Extension.LOWERCASE); }
    try {
        app.displayDialogs=DialogModes.NO;
        if(ExternalObject.AdobeXMPScript===undefined) { ExternalObject.AdobeXMPScript=new ExternalObject("lib:AdobeXMPScript"); }
        var root=app.open(new File(input));owned.push(root);
        png(root,beforePng);
        var before=inspect(root,0);
        app.activeDocument=root;
        if(/\.psb$/i.test(roundtrip)) {
            // PSB has no Photoshop DOM SaveOptions constructor in Photoshop 21.
            var save=new ActionDescriptor(),format=new ActionDescriptor();
            format.putBoolean(stringIDToTypeID("maximizeCompatibility"),true);
            save.putObject(charIDToTypeID("As  "),stringIDToTypeID("largeDocumentFormat"),format);
            save.putPath(charIDToTypeID("In  "),new File(roundtrip));
            save.putBoolean(charIDToTypeID("Cpy "),true);
            save.putBoolean(charIDToTypeID("LwCs"),true);
            executeAction(charIDToTypeID("save"),save,DialogModes.NO);
        } else {
            var options=new PhotoshopSaveOptions();options.layers=true;
            root.saveAs(new File(roundtrip),options,true,Extension.LOWERCASE);
        }
        root.close(SaveOptions.DONOTSAVECHANGES);owned.pop();
        var reopened=app.open(new File(roundtrip));owned.push(reopened);
        png(reopened,afterPng);
        var after=inspect(reopened,0);
        reopened.close(SaveOptions.DONOTSAVECHANGES);owned.pop();
        return encode([before,after]);
    } catch(e) {
        failed=true;
        throw new Error("Host acceptance: " + e.message + " (line " + e.line + ")");
    } finally {
        for(var k=owned.length-1;k>=0;k--){try{owned[k].close(SaveOptions.DONOTSAVECHANGES);}catch(e){}}
        try { app.displayDialogs=oldDialogs; } catch(restoreError) { if(!failed) { throw restoreError; } }
    }
})();
'''


def main() -> int:
    parser = argparse.ArgumentParser(description="空闲 Photoshop 会话中的真实结果打开、编辑及保存重开验收")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="必须尚不存在的隔离验证目录")
    parser.add_argument("--timeout", type=int, default=180, help="整次验证时限；超时只退出本验证进程，不结束 Photoshop")
    args = parser.parse_args()
    import pythoncom
    import win32com.client
    from PIL import Image
    from prototype.batch import atomic_json, sha256_file
    report = json.loads(args.report.read_text(encoding="utf-8"))
    output = args.output.resolve()
    if args.report.resolve().parent not in output.parents:
        raise ValueError("验证输出必须位于验收报告的隔离目录内")
    # Prevent validation writes into either source or JSX reference trees.
    for record in report["samples"]:
        protected = Path(record["batch"]["source"]).resolve().parent
        if output == protected or protected in output.parents or output in protected.parents:
            raise ValueError("验证目录必须与原稿目录独立")
    pythoncom.CoInitialize()
    checks: list[dict[str, Any]] = []
    created = False
    watchdog = None
    try:
        app = win32com.client.GetActiveObject("Photoshop.Application")
        app._FlagAsMethod("DoJavaScript")
        if int(app.Documents.Count):
            raise ValueError("请使用没有打开任何文档的空闲 Photoshop 会话验收")
        version = str(app.Version)
        output.mkdir(parents=True, exist_ok=False)
        created = True
        if args.timeout <= 0:
            raise ValueError("timeout 必须为正数")
        def timed_out():
            atomic_json(output / "host-failure.json", {"status": "timeout", "completed": checks,
                        "note": "只终止验证进程。Photoshop 中的隔离副本可能仍打开，需人工检查；不自动重试或结束 Photoshop。"})
            os._exit(124)
        watchdog = threading.Timer(args.timeout, timed_out)
        watchdog.daemon = True
        watchdog.start()
        for record in report["samples"]:
            source = Path(record["batch"]["output"])
            before_hash = sha256_file(source)
            relative = Path(record.get("sample_relative_path", source.name))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("验收记录包含非法相对路径")
            directory = output / relative
            directory.mkdir(parents=True)
            fixture = directory / source.name
            shutil.copy2(source, fixture)
            chain = deepest_chain(fixture.read_bytes())
            saved = directory / ("roundtrip" + source.suffix)
            script = SCRIPT
            for key, value in {"__INPUT__": str(fixture), "__ROUNDTRIP__": str(saved),
                               "__BEFORE__": str(directory / "before.png"), "__AFTER__": str(directory / "after.png"),
                               "__CHAIN__": chain}.items():
                script = script.replace(key, json.dumps(value, ensure_ascii=True))
            before, after = json.loads(str(app.DoJavaScript(script)))
            with Image.open(directory / "before.png") as image:
                left = image.convert("RGBA")
            with Image.open(directory / "after.png") as image:
                right = image.convert("RGBA")
            entry = {"sample": source.name, "photoshop_version": version, "nested_depth_opened": len(chain),
                     "ancestors_absent_before": all(not row[1] for row in before),
                     "ancestors_absent_after": all(not row[1] for row in after),
                     "layers_equal_after_save_reopen": before == after,
                     "render_equal_after_save_reopen": left.size == right.size and left.tobytes() == right.tobytes(),
                     "python_output_unchanged": sha256_file(source) == before_hash,
                     "snapshot_before_sha256": hashlib.sha256(json.dumps(before, ensure_ascii=True).encode()).hexdigest(),
                     "snapshot_after_sha256": hashlib.sha256(json.dumps(after, ensure_ascii=True).encode()).hexdigest(),
                     "documents_after": int(app.Documents.Count)}
            checks.append(entry)
            atomic_json(output / "host-report.json", checks)
            print(json.dumps(entry, ensure_ascii=True), flush=True)
        return int(not all(c[flag] for c in checks for flag in ("ancestors_absent_before", "ancestors_absent_after",
                       "layers_equal_after_save_reopen", "render_equal_after_save_reopen", "python_output_unchanged")))
    except Exception as exc:
        if created:
            atomic_json(output / "host-failure.json", {"status": "failed", "completed": checks,
                        "error": str(exc), "note": "本次未完成，不计为通过。"})
        raise
    finally:
        if watchdog is not None:
            watchdog.cancel()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
