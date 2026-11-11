// The send check on the log form. Run by `inv test` with `node --test`.
const test = require("node:test");
const assert = require("node:assert");
const { markRecipients } = require("../../src/odas/static/log_form.js");

const known = ["a.kok@example.nl", "emma@example.nl"];

test("an address that is neither the indiener nor a colleague is marked", () => {
    assert.deepStrictEqual(markRecipients("n.boer@provincie.example.nl", known), [
        { text: "n.boer@provincie.example.nl", unknown: true },
    ]);
});

test("the indiener and a colleague are not marked, whatever the case of the letters", () => {
    const marked = markRecipients("Arjen Kok <A.Kok@Example.nl>, emma@example.nl", known);

    assert.deepStrictEqual(marked.map(r => r.unknown), [false, false]);
    assert.strictEqual(marked[0].text, "Arjen Kok <A.Kok@Example.nl>");
});

test("a comma inside a quoted name keeps the name with its address", () => {
    const marked = markRecipients('"Boer, Niek" <n.boer@provincie.example.nl>, a.kok@example.nl', known);

    assert.deepStrictEqual(marked, [
        { text: '"Boer, Niek" <n.boer@provincie.example.nl>', unknown: true },
        { text: "a.kok@example.nl", unknown: false },
    ]);
});
