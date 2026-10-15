# Requests from S9D (files not owned by S9D)
1. anonymizer/addin.py `/api/addin/open-app`: accept `settings: true` and make the main window open its settings dialog (the add-in server serves no settings page; the main app is a separate server). The pane already sends `{tab:"anon", settings:true}`; today it only focuses the app window and tells the user to use the profile icon.
2. anonymizer/addin.py `info()`: optionally add `image_mode` and `ner_available` to `prefs`; the pane currently reads them from `/api/state` (image_mode_unsafe, ner_available), which the add-in handler already serves.
