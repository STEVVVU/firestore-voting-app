# Vote and results

## Sub-features
Authenticate, cast one choice, inspect counts and recent choices.

## How to get to it (user POV)
Open the app, sign in, choose tabs or spaces.

## Driving it with HTTP
Send a bearer-authenticated POST /votes followed by GET /results.

## Gotchas
Live Google identity and Firestore require separately configured cloud resources; local substitutes cannot prove those integrations.
