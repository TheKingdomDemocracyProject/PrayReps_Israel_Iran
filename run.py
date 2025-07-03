from project import create_app
import os
import sys

app = create_app()

if __name__ == "__main__":
    try:
        # Port for Render, default to 5000 for local dev
        port = int(os.environ.get("PORT", 5000))

        # Note: app.py's original initialize_app_data() logic will be called
        # during create_app() or explicitly afterwards if refactored.
        # For local dev, app.run() might cause another load if reloader is on.
        # For Gunicorn, it's fine as create_app is called once per worker.

        # Example of how initial data loading might be triggered if it's not inside create_app
        # with app.app_context():
        #    from project.data_loader import initialize_app_data
        #    initialize_app_data(app)

        app.run(debug=True, host="0.0.0.0", port=port)
    except KeyboardInterrupt:
        print("You pressed Ctrl+C! Exiting gracefully...")
        sys.exit(0)
    except Exception as e:
        # This is a good place to log any startup errors if logging isn't fully up yet
        print(f"Failed to start application: {e}")
        sys.exit(1)
