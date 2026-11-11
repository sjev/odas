// The drafts kept in the browser. Run by `inv test` with `node --test`.
const test = require("node:test");
const assert = require("node:assert");
const drafts = require("../../src/odas/static/drafts.js");

test("a draft typed in a form comes back when the page opens again", () => {
    const typed = { onderwerp: "Vraag gevoegde behandeling", aan: "elsbeth@example.nl", body: "Beste Elsbeth, ..." };
    drafts.save("/zaken/zk-22902:log-form", typed);

    assert.deepStrictEqual(drafts.load("/zaken/zk-22902:log-form"), typed);
});

test("a sent or cancelled form leaves no draft behind", () => {
    drafts.save("/zaken/zk-22902:log-form", { body: "Beste Elsbeth" });
    drafts.drop("/zaken/zk-22902:log-form");

    assert.strictEqual(drafts.load("/zaken/zk-22902:log-form"), null);
});

test("logging out removes every draft", () => {
    drafts.save("/zaken/zk-22902:log-form", { body: "Beste Elsbeth" });
    drafts.save("/zaken/zk-22902/bewerken:zaak", { body: "Samenvatting" });
    drafts.dropAll();

    assert.strictEqual(drafts.load("/zaken/zk-22902:log-form"), null);
    assert.strictEqual(drafts.load("/zaken/zk-22902/bewerken:zaak"), null);
});

test("a draft older than two weeks does not come back", () => {
    const fifteenDaysAgo = Date.now() - 15 * 24 * 3600 * 1000;
    drafts.save("/zaken/zk-22902:log-form", { body: "Beste Elsbeth" }, null, fifteenDaysAgo);

    assert.strictEqual(drafts.load("/zaken/zk-22902:log-form"), null);
});

test("a draft of an edit page does not come back over a newer saved text", () => {
    drafts.save("/zaken/zk-22902/bewerken:zaak", { body: "mijn versie" }, { body: "oud" });

    assert.strictEqual(drafts.load("/zaken/zk-22902/bewerken:zaak", { body: "door een collega gewijzigd" }), null);
    assert.deepStrictEqual(drafts.load("/zaken/zk-22902/bewerken:zaak", { body: "oud" }), { body: "mijn versie" });
});

test("a browser that blocks storage still keeps the draft while the page is open", () => {
    drafts.use({ getItem() { throw new Error("SecurityError"); } });
    drafts.save("/zaken/zk-22902:log-form", { body: "Beste Elsbeth" });

    assert.deepStrictEqual(drafts.load("/zaken/zk-22902:log-form"), { body: "Beste Elsbeth" });
});
