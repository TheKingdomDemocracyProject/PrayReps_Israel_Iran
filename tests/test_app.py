"""Basic application tests."""


def test_app_creation(client):
    """Test if the Flask app instance is created and a simple request to / works."""
    response = client.get("/")
    assert response.status_code == 200
    # Depending on the home page content, more assertions can be added.
    # For now, just checking if it loads.


# Example of how to test another route if needed:
# def test_about_page(client):
#     """Test the about page."""
#     response = client.get("/about")
#     assert response.status_code == 200
#     assert b"About" in response.data # Assuming "About" is in the page title or body
