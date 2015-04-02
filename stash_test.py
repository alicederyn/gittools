from stash import Stash

def test_url_host_can_start_with_stash():
  assert Stash._getStashHostname("https://stash.yojoe.local/bob") == "stash.yojoe.local"

def test_url_host_can_be_only_stash():
  assert Stash._getStashHostname("https://stash/bob") == "stash"

def test_url_host_cannot_be_stashattack():
  assert Stash._getStashHostname("https://stashattack") is None

def test_git_host_can_start_with_stash():
  assert Stash._getStashHostname("git@stash.yojoe.local:bob") == "stash.yojoe.local"

def test_git_host_can_be_only_stash():
  assert Stash._getStashHostname("git@stash:bob") == "stash"

def test_git_host_cannot_be_missing_name_of_repo():
  assert Stash._getStashHostname("git@stash") is None

def test_git_host_cannot_be_stashattack():
  assert Stash._getStashHostname("git@stashattack:bob") is None
