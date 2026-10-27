# Browser results

## Sub-features
View public totals and recent entries; sign in and vote if Firebase is configured.

## How to get to it (user POV)
Open the root page. Totals appear without signing in; voting requires Google sign-in.

## Driving it with CUA
Start the app as described in the README and open its URL with CUA. Check the displayed totals against `/results`, and check that vote buttons are disabled without sign-in. With a separately authorized Firebase setup, sign in and vote and verify the result and persisted state; do not use a real personal account as a synthetic test identity without permission.

## Gotchas
The local synthetic API identity is not exposed through the browser. The configured sign-in journey remains unverified; the course template rendering and a populated local state were inspected at desktop size only.
