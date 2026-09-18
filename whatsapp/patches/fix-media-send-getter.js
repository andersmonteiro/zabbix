// Patches a confirmed whatsapp-web.js bug: sending media fails with
// "Data passed to getter must include an id property (it's how we memoize)
// but got undefined" because processMediaData()'s internal __x_id property
// collides with the outgoing message's own id field.
// Upstream issue (open, unreleased as of this writing):
// https://github.com/wwebjs/whatsapp-web.js/issues/201922
// Fix verified against commit 78924ae. Remove this patch once whatsapp-web.js
// ships an official release containing that fix.
const fs = require('fs');

const path = 'node_modules/whatsapp-web.js/src/util/Injected/Utils.js';
const marker = "// Bot's won't reply if canonicalUrl is set (linking)";
const fixLine = 'delete message.__x_id;';

const content = fs.readFileSync(path, 'utf8');

if (content.includes(fixLine)) {
    console.log('[fix-media-send-getter] Already patched, skipping.');
    process.exit(0);
}

if (!content.includes(marker)) {
    console.error(
        '[fix-media-send-getter] Marker not found — whatsapp-web.js internals ' +
        'have likely changed (possibly because the upstream fix already shipped). ' +
        'Check https://github.com/wwebjs/whatsapp-web.js/issues/201922 and remove ' +
        'this patch if so.'
    );
    process.exit(1);
}

const patched = content.replace(marker, `${fixLine}\n\n        ${marker}`);
fs.writeFileSync(path, patched);
console.log('[fix-media-send-getter] Patched successfully.');
