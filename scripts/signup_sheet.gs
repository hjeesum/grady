/**
 * Google Apps Script for the sign-up form's answers Sheet (Extensions > Apps Script).
 *
 * Deployed as a web app, it does two things:
 * 1. With ?key=KEY: returns the signed-up email addresses, one per line, plus
 *    "-address" lines for people who unsubscribed (so Grady also drops them from
 *    the SUBSCRIBERS secret). Grady's daily run reads this.
 * 2. With ?action=unsubscribe&email=...&token=...: the link at the bottom of each
 *    email. It asks "are you sure?" first, because some email security scanners
 *    open every link in an email by themselves.
 *
 * The token is an HMAC of the address made with KEY (grady/emailer.py makes the
 * same one), so nobody can unsubscribe someone else by editing the link.
 * The key is NOT in this file (this repository is public): it's saved in the
 * script's Project Settings > Script Properties as KEY.
 * After changing this code: Deploy > Manage deployments > edit > Version: New
 * version, so the web address stays the same.
 */
const UNSUBSCRIBED_SHEET = "Unsubscribed";

function doGet(e) {
  const key = PropertiesService.getScriptProperties().getProperty("KEY");
  if (e.parameter.action === "unsubscribe") {
    return unsubscribe(e.parameter, key);
  }
  if (!key || e.parameter.key !== key) {
    return ContentService.createTextOutput("ERROR: wrong key");
  }
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const column = emailColumn(sheet);
  if (column < 0) {
    return ContentService.createTextOutput("ERROR: no email column");
  }
  const emails = sheet.getDataRange().getValues().slice(1)
    .map(row => String(row[column]).trim().toLowerCase()).filter(Boolean);
  // Someone who unsubscribed and later signed up again has a new row: keep them.
  const signedUp = new Set(emails);
  const removed = unsubscribedSheet().getDataRange().getValues().slice(1)
    .map(row => String(row[1]).trim().toLowerCase())
    .filter(email => email && !signedUp.has(email));
  const lines = emails.concat([...new Set(removed)].map(email => "-" + email));
  return ContentService.createTextOutput(lines.join("\n"));
}

function unsubscribe(p, key) {
  const email = String(p.email || "").trim().toLowerCase();
  if (!key || !email || p.token !== token(email, key)) {
    return page("This unsubscribe link isn't complete. Reply to any Grady email and you'll be removed by hand.");
  }
  if (p.confirm !== "yes") {
    const url = ScriptApp.getService().getUrl() + "?action=unsubscribe&email=" +
      encodeURIComponent(email) + "&token=" + p.token + "&confirm=yes";
    return page("Stop Grady's daily job emails to <b>" + escapeHtml(email) + "</b>?<br><br>" +
      '<a href="' + url + '" target="_top" style="background:#0969da;color:#fff;padding:10px 18px;' +
      'border-radius:6px;text-decoration:none;font-weight:600;">Yes, unsubscribe me</a>');
  }
  // Delete their sign-up rows (bottom up, so the row numbers don't shift) and
  // remember them, in case they're in the SUBSCRIBERS secret too.
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  const column = emailColumn(sheet);
  const rows = sheet.getDataRange().getValues();
  for (let i = rows.length - 1; i >= 1; i--) {
    if (column >= 0 && String(rows[i][column]).trim().toLowerCase() === email) {
      sheet.deleteRow(i + 1);
    }
  }
  unsubscribedSheet().appendRow([new Date(), email]);
  return page("Done. You won't get any more emails from Grady. Changed your mind? Sign up again on the job page.");
}

function emailColumn(sheet) {
  // Google Forms names the column "Email address" (or "Email Address").
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  return headers.findIndex(header => String(header).toLowerCase().includes("email"));
}

function unsubscribedSheet() {
  const spreadsheet = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = spreadsheet.getSheetByName(UNSUBSCRIBED_SHEET);
  if (!sheet) {
    // Added last, so the form's answers stay the first tab (getSheets()[0]).
    sheet = spreadsheet.insertSheet(UNSUBSCRIBED_SHEET, spreadsheet.getSheets().length);
    sheet.appendRow(["When", "Email"]);
  }
  return sheet;
}

function token(email, key) {
  // Same as Python's hmac.new(key, email, sha256).hexdigest().
  return Utilities.computeHmacSha256Signature(email, key)
    .map(b => ((b + 256) % 256).toString(16).padStart(2, "0")).join("");
}

function page(body) {
  return HtmlService.createHtmlOutput(
    '<div style="font:16px/1.5 system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;">' +
    "<h2>Grady</h2><p>" + body + "</p></div>").setTitle("Grady: unsubscribe");
}

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}
