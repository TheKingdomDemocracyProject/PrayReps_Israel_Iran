def test_home_page(client):
    """Test that the home page loads."""
    response = client.get("/")
    assert response.status_code == 200


def test_queue_page(client):
    """Test that the queue page loads."""
    response = client.get("/prayer/queue_page")
    assert response.status_code == 200


def test_prayed_overall_page(client):
    """Test that the overall prayed page loads."""
    response = client.get("/prayer/prayed_list_page/overall")
    assert response.status_code == 200


def test_statistics_overall_page(client):
    """Test that the overall statistics page loads."""
    response = client.get("/stats/overall")
    assert response.status_code == 200


def test_israel_map_generation(client):
    """Test generation of Israel map."""
    response = client.get("/generate_map_for_country_json/israel")
    assert response.status_code == 200
    assert response.content_type == "application/json"  # This route returns JSON


def test_iran_map_generation(client):
    """Test generation of Iran map."""
    response = client.get("/generate_map_for_country_json/iran")
    assert response.status_code == 200
    assert response.content_type == "application/json"  # This route returns JSON
