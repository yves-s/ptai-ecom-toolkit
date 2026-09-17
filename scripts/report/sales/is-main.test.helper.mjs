// Hilfsprogramm für is-main.test.mjs: importiert db.mjs so, wie send-report.mjs
// es tut, und zwar mit einem argv, das db.mjs als Befehl deuten würde. Greift
// der CLI-Zweig beim Import, meldet db.mjs "unknown cmd" und bricht ab.
await import('./db.mjs');
console.log('importiert-ohne-cli');
