// Explicit opt-in acceptance: all edits are to an isolated copy supplied by Python.
(function () {
    var plan = __PLAN__;
    if (app.documents.length !== 0) { throw new Error("Requires an empty Photoshop session"); }
    var owned = [], oldDialogs = app.displayDialogs;
    function log(message) {
        var f = new File(plan.log);
        if (!f.open("a")) { throw new Error("Cannot append host stage log"); }
        f.writeln(new Date().getTime() + " " + message); f.close();
    }
    function check(condition, message) { if (!condition) { throw new Error(message); } }
    function select(doc, id) {
        app.activeDocument = doc;
        var ref = new ActionReference(); ref.putIdentifier(charIDToTypeID("Lyr "), id);
        var d = new ActionDescriptor(); d.putReference(charIDToTypeID("null"), ref);
        d.putBoolean(charIDToTypeID("MkVs"), false);
        executeAction(charIDToTypeID("slct"), d, DialogModes.NO);
    }
    function openChild(doc, id) {
        select(doc, id);
        var count = app.documents.length;
        executeAction(stringIDToTypeID("placedLayerEditContents"), new ActionDescriptor(), DialogModes.NO);
        check(app.documents.length === count + 1 && app.activeDocument !== doc, "Embedded document did not open independently");
        var child = app.activeDocument; owned.push(child); return child;
    }
    function closeChild(child, save) {
        app.activeDocument = child;
        if (save) { child.save(); }
        child.close(SaveOptions.DONOTSAVECHANGES); owned.pop();
    }
    function hasMarker(doc, marker) {
        // getByName avoids walking large DOM collections; markers are root art layers.
        try { return doc.artLayers.getByName(marker).name === marker; }
        catch (e) {
            // Do not treat an arbitrary host failure as evidence of absence.
            // AM enumerate names to confirm an absent marker independently.
            app.activeDocument = doc;
            var r = new ActionReference();
            r.putProperty(stringIDToTypeID("property"), stringIDToTypeID("numberOfLayers"));
            r.putEnumerated(charIDToTypeID("Dcmn"), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
            var count = executeActionGet(r).getInteger(stringIDToTypeID("numberOfLayers"));
            for (var i = 1; i <= count; i++) {
                var lr = new ActionReference(); lr.putIndex(charIDToTypeID("Lyr "), i);
                if (executeActionGet(lr).getString(stringIDToTypeID("name")) === marker) { return true; }
            }
            return false;
        }
    }
    function addMarker(doc, marker) {
        app.activeDocument = doc;
        var layer = doc.artLayers.add(); layer.name = marker; layer.visible = false;
        check(hasMarker(doc, marker), "Could not create editable art layer");
    }
    function deep(doc, depth, edit) {
        if (depth === plan.chain.length) {
            var found = hasMarker(doc, plan.deepMarker);
            if (edit) {
                check(!found, "Deep marker already exists before edit");
                if (plan.edit) { addMarker(doc, plan.deepMarker); }
                return true;
            }
            return found;
        }
        log((edit ? "edit" : "verify") + " depth " + depth);
        var child = openChild(doc, plan.chain[depth]);
        var result = deep(child, depth + 1, edit);
        closeChild(child, edit);
        return result;
    }
    function shared(doc, id, edit) {
        var child = openChild(doc, id);
        var found = hasMarker(child, plan.sharedMarker);
        if (edit) {
            check(!found, "Shared marker already exists before edit");
            if (plan.edit) { addMarker(child, plan.sharedMarker); }
        }
        closeChild(child, edit);
        return found;
    }
    function png(doc, path) {
        app.activeDocument = doc;
        doc.saveAs(new File(path), new PNGSaveOptions(), true, Extension.LOWERCASE);
    }
    function saveRoot(doc) {
        app.activeDocument = doc;
        if (/\.psb$/i.test(plan.saved)) {
            var d = new ActionDescriptor(), format = new ActionDescriptor();
            format.putBoolean(stringIDToTypeID("maximizeCompatibility"), true);
            d.putObject(charIDToTypeID("As  "), stringIDToTypeID("largeDocumentFormat"), format);
            d.putPath(charIDToTypeID("In  "), new File(plan.saved));
            d.putBoolean(charIDToTypeID("Cpy "), true); d.putBoolean(charIDToTypeID("LwCs"), true);
            executeAction(charIDToTypeID("save"), d, DialogModes.NO);
        } else {
            var options = new PhotoshopSaveOptions(); options.layers = true;
            doc.saveAs(new File(plan.saved), options, true, Extension.LOWERCASE);
        }
    }
    try {
        app.displayDialogs = DialogModes.NO;
        log("open isolated root");
        var root = app.open(new File(plan.input)); owned.push(root);
        png(root, plan.beforePng);
        check(!deep(root, 0, false), "Deep marker exists before edit");
        check(!shared(root, plan.shared[0], false) && !shared(root, plan.shared[1], false), "Shared marker exists before edit");
        log("deep edit and propagate saves");
        deep(root, 0, true);
        check(deep(root, 0, false) === plan.edit, "Unexpected deep marker state after save");
        log("edit shared first instance");
        shared(root, plan.shared[0], true);
        check(shared(root, plan.shared[1], false) === plan.edit, "Unexpected shared peer state after save");
        png(root, plan.editedPng);
        log("save root"); saveRoot(root);
        root.close(SaveOptions.DONOTSAVECHANGES); owned.pop();
        log("reopen root");
        root = app.open(new File(plan.saved)); owned.push(root);
        check(deep(root, 0, false) === plan.edit, "Unexpected deep marker state after reopen");
        check(shared(root, plan.shared[0], false) === plan.edit, "Unexpected first shared marker state after reopen");
        check(shared(root, plan.shared[1], false) === plan.edit, "Unexpected shared peer marker state after reopen");
        png(root, plan.afterPng);
        root.close(SaveOptions.DONOTSAVECHANGES); owned.pop();
        log("all edit and linkage checks passed");
        return "passed";
    } catch (e) {
        log("failed: " + e.message + " line " + e.line);
        throw e;
    } finally {
        for (var i = owned.length - 1; i >= 0; i--) {
            try { owned[i].close(SaveOptions.DONOTSAVECHANGES); } catch (e) {}
        }
        app.displayDialogs = oldDialogs;
    }
})();
