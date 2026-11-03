/**
 * Google Apps Script for the sign-up form's answers Sheet (Extensions > Apps Script).
 *
 * Deployed as a web app, it returns the signed-up email addresses, one per line,
 * but only to a request carrying the secret key. Grady's daily run reads it, so a
 * friend who signs up gets the next morning's email with nothing to do by hand.
 *
 * The key is NOT in this file (this repository is public): it's saved in the
 * script's Project Settings > Script Properties as KEY.
 * To unsubscribe someone, delete their row in the Sheet.
 */
function doGet(e) {
  const key = PropertiesService.getScriptProperties().getProperty("KEY");
  if (!key || e.parameter.key !== key) {
    return ContentService.createTextOutput("ERROR: wrong key");
  }
  const rows = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0].getDataRange().getValues();
  // Google Forms names the column "Email address" (or "Email Address").
  const column = rows[0].findIndex(header => String(header).toLowerCase().includes("email"));
  if (column < 0) {
    return ContentService.createTextOutput("ERROR: no email column");
  }
  const emails = rows.slice(1).map(row => String(row[column]).trim()).filter(Boolean);
  return ContentService.createTextOutput(emails.join("\n"));
}
