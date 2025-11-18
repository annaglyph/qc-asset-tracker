// Check_QC_Sidecars.jsx (updated)
// ------------------------------------------------
// - Works on selection or all project items
// - Reads QC sidecars and updates [[QC: STATUS]] in the Comment column
// - Only rewrites the QC tag when status changes
// - Uses qc_result / qc_status / status as possible fields

// ----------------------
// CONFIGURATION
// ----------------------
var QC_CONFIG = {
    // Candidate sidecar names (in order of priority)
    // ${DIR}    -> folder containing the media file
    // ${STEM}   -> filename without extension
    patterns: [
        "${DIR}/.qc/sequence.qc.json",
        "${DIR}/.qc/${STEM}.qc.json",
        "${DIR}/${STEM}.qc.json"
    ],

    // Field paths to try for status and summary (first non-empty wins)
    statusFields: [
        "qc_result",
        "qc_status",
        "qc.status",
        "status"
    ],
    summaryFields: [
        "qc_summary",
        "qc.summary",
        "summary",
        "note"
    ],

    // Label indices (AE's label colours are 1..16)
    labels: {
        PASS: 9,     // typically a green-ish label
        FAIL: 2,     // typically a red-ish label
        PENDING: 4,   // often a yellow-ish label
        MISSING: 0,      // grey/neutral
        UNAVAILABLE: 0   // grey/neutral
    },

    // Comment QC tag prefix (used inside [[ ... ]])
    qcTagPrefix: "QC"
};

// ----------------------
// UTILITY FUNCTIONS
// ----------------------

function log(msg) {
    $.writeln("[QC] " + msg);
}

function readFileText(file) {
    if (!file || !file.exists) {
        return null;
    }
    if (!file.open("r")) {
        return null;
    }
    var txt = file.read();
    file.close();
    return txt;
}

function parseJSONSafe(text) {
    if (!text || text === "") {
        return null;
    }
    try {
        if (typeof JSON !== "undefined" && JSON.parse) {
            return JSON.parse(text);
        } else {
            // Fallback for older ExtendScript environments
            return eval("(" + text + ")");
        }
    } catch (e) {
        log("JSON parse error: " + e.toString());
        return null;
    }
}

function getStemFromFile(file) {
    var name = file.name; // includes extension
    var lastDot = name.lastIndexOf(".");
    if (lastDot > 0) {
        return name.substring(0, lastDot);
    }
    return name;
}

// Simple "get nested field" helper, e.g. path "qc.status"
function getFieldByPath(obj, path) {
    if (!obj || !path) return null;
    var parts = path.split(".");
    var current = obj;
    for (var i = 0; i < parts.length; i++) {
        if (current[parts[i]] === undefined) return null;
        current = current[parts[i]];
    }
    return current;
}

function normalizeStatus(raw) {
    if (!raw) return "UNKNOWN";
    var s = ("" + raw).toLowerCase();

    if (s === "pass" || s === "success") {
        return "PASS";
    }
    if (s === "fail" || s === "error") {
        return "FAIL";
    }
    if (s === "pending" || s === "in_progress") {
        return "PENDING";
    }
    return "UNKNOWN";
}

// Additional manual statuses
function statusMissing() { return "MISSING"; }

function statusUnavailable() { return "UNAVAILABLE"; }

function findSidecarForFile(mediaFile) {
    var dir = mediaFile.parent; // Folder object
    if (!dir || !dir.exists) {
        return null;
    }

    var dirPath = dir.fsName;
    var stem = getStemFromFile(mediaFile);

    for (var i = 0; i < QC_CONFIG.patterns.length; i++) {
        var pattern = QC_CONFIG.patterns[i];
        var fullPath = pattern
            .replace("${DIR}", dirPath)
            .replace("${STEM}", stem);

        var sidecarFile = new File(fullPath);
        if (sidecarFile.exists) {
            return sidecarFile;
        }
    }

    return null;
}

function extractStatusAndSummary(jsonObj) {
    var status = null;
    var summary = null;

    // find status
    for (var i = 0; i < QC_CONFIG.statusFields.length; i++) {
        var v = getFieldByPath(jsonObj, QC_CONFIG.statusFields[i]);
        if (v !== null && v !== undefined && v !== "") {
            status = v;
            break;
        }
    }

    // find summary
    for (var j = 0; j < QC_CONFIG.summaryFields.length; j++) {
        var s = getFieldByPath(jsonObj, QC_CONFIG.summaryFields[j]);
        if (s !== null && s !== undefined && s !== "") {
            summary = s;
            break;
        }
    }

    return {
        status: normalizeStatus(status),
        summary: summary
    };
}

// Parse an existing [[QC: STATUS]] at the beginning of a comment
function parseExistingQCTag(comment) {
    if (!comment) return null;

    var re = new RegExp("^\\s*\\[\\[" + QC_CONFIG.qcTagPrefix + ":\\s*([^\\]]+)\\]\\]");
    var m = comment.match(re);
    if (!m || m.length < 2) {
        return null;
    }
    // Normalise status text extracted from tag
    var raw = m[1];
    var norm = normalizeStatus(raw);
    return {
        raw: raw,
        normalized: norm
    };
}

// Build updated comment with [[QC: STATUS]] tag
// - If existing tag present AND status unchanged => return existing comment as-is
// - If tag present & status changed => replace tag
// - If no tag => prepend new tag
function buildCommentWithQCTag(existingComment, statusStr, summary) {
    var newTag = "[[" + QC_CONFIG.qcTagPrefix + ": " + statusStr + "]]";

    if (!existingComment || existingComment === "") {
        // Just tag + optional summary
        if (summary && summary !== "") {
            return newTag + " " + summary;
        }
        return newTag;
    }

    var existing = parseExistingQCTag(existingComment);
    if (existing && existing.normalized === statusStr) {
        // Status unchanged -> keep comment exactly as-is
        return existingComment;
    }

    if (existing) {
        // Replace only the first tag
        var re = new RegExp("^\\s*\\[\\[" + QC_CONFIG.qcTagPrefix + ":\\s*[^\\]]+\\]\\]");
        var replaced = existingComment.replace(re, newTag);
        return replaced;
    } else {
        // No existing tag: prepend tag to comment
        var base = newTag;
        if (summary && summary !== "") {
            base += " " + summary;
        }
        return base + " | " + existingComment;
    }
}

function applyLabelForStatus(item, status) {
    if (!item) return;

    if (status === "PASS" && QC_CONFIG.labels.PASS) {
        item.label = QC_CONFIG.labels.PASS;
    } else if (status === "FAIL" && QC_CONFIG.labels.FAIL) {
        item.label = QC_CONFIG.labels.FAIL;
    } else if (status === "PENDING" && QC_CONFIG.labels.PENDING) {
        item.label = QC_CONFIG.labels.PENDING;
    }
    // UNKNOWN -> leave label as-is
}

// ----------------------
// MAIN
// ----------------------

function getTargetItems(project) {
    var selected = project.selection;
    if (selected && selected.length > 0) {
        return selected;
    }

    // Otherwise, all project items
    var all = [];
    for (var i = 1; i <= project.numItems; i++) {
        all.push(project.item(i));
    }
    return all;
}

function checkQCSidecars() {
    if (!app.project) {
        alert("No project open.");
        return;
    }

    app.beginUndoGroup("Check QC Sidecars");

    var items = getTargetItems(app.project);
    var processed = 0;
    var withSidecar = 0;
    var noSidecar = 0;
    var parseErrors = 0;

    for (var i = 0; i < items.length; i++) {
        var item = items[i];

        // Only handle footage items with a file on disk
        if (!(item instanceof FootageItem)) {
            continue;
        }
        if (!item.file || !item.file.exists) {
            continue;
        }

        processed++;

        var sidecarFile = findSidecarForFile(item.file);
        if (!sidecarFile) {
            noSidecar++;
            log("No sidecar for: " + item.name + " (" + item.file.fsName + ")");

            // Mark as [[QC: MISSING]]
            var status = statusMissing();
            item.comment = buildCommentWithQCTag(item.comment, status, "No QC sidecar found.");
            applyLabelForStatus(item, status);

            continue;
        }


        var jsonText = readFileText(sidecarFile);
        var jsonObj = parseJSONSafe(jsonText);

        if (!jsonObj) {
            parseErrors++;
            log("Failed to parse JSON for: " + item.name + " (" + sidecarFile.fsName + ")");

            var status = statusUnavailable();
            item.comment = buildCommentWithQCTag(item.comment, status, "Sidecar unreadable.");
            applyLabelForStatus(item, status);

            continue;
        }


        var info = extractStatusAndSummary(jsonObj);
        var statusNorm = info.status;
        var summary = info.summary;

        log("Item: " + item.name + " | Sidecar: " + sidecarFile.fsName + " | Status: " + statusNorm);

        // Update comment (only if status changed or no tag yet)
        item.comment = buildCommentWithQCTag(item.comment, statusNorm, summary);

        // Update label
        applyLabelForStatus(item, statusNorm);

        withSidecar++;
    }

    app.endUndoGroup();

    var report =
        "QC Check complete.\n\n" +
        "Footage items processed: " + processed + "\n" +
        "With sidecar: " + withSidecar + "\n" +
        "Without sidecar: " + noSidecar + "\n" +
        "Sidecars with parse errors: " + parseErrors + "\n\n" +
        "Tip: Select specific items in the Project panel to limit the check.";

    alert(report);
}

// Run it
checkQCSidecars();
