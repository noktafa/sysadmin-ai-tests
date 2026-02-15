import pytest

from infra.os_matrix import OSTarget, get_all, get_by_family, get_by_name, get_by_pkg_manager


class TestOSTarget:
    def test_attributes_stored(self):
        t = OSTarget(
            name="test-os",
            image="test-os-x64",
            user="admin",
            pkg_manager="apt",
            family="debian",
            python_install="apt-get install -y python3",
            setup_commands=["apt-get update"],
        )
        assert t.name == "test-os"
        assert t.image == "test-os-x64"
        assert t.user == "admin"
        assert t.pkg_manager == "apt"
        assert t.family == "debian"
        assert t.python_install == "apt-get install -y python3"
        assert t.setup_commands == ["apt-get update"]

    def test_setup_commands_defaults_to_empty_list(self):
        t = OSTarget(name="x", image="x-x64")
        assert t.setup_commands == []

    def test_repr(self):
        t = OSTarget(name="ubuntu-24.04", image="ubuntu-24-04-x64", family="debian")
        r = repr(t)
        assert "ubuntu-24.04" in r
        assert "ubuntu-24-04-x64" in r
        assert "debian" in r

    def test_eq_same(self):
        a = OSTarget(name="a", image="a-x64")
        b = OSTarget(name="a", image="a-x64")
        assert a == b

    def test_eq_different(self):
        a = OSTarget(name="a", image="a-x64")
        b = OSTarget(name="b", image="b-x64")
        assert a != b

    def test_eq_not_implemented_for_other_types(self):
        t = OSTarget(name="a", image="a-x64")
        assert t.__eq__("not-an-ostarget") is NotImplemented


class TestMatrixIntegrity:
    def test_not_empty(self):
        assert len(get_all()) > 0

    def test_all_ostarget_instances(self):
        for t in get_all():
            assert isinstance(t, OSTarget)

    def test_unique_names(self):
        names = [t.name for t in get_all()]
        assert len(names) == len(set(names))

    def test_unique_images(self):
        images = [t.image for t in get_all()]
        assert len(images) == len(set(images))

    def test_images_end_with_x64(self):
        for t in get_all():
            assert t.image.endswith("-x64"), f"{t.name} image does not end with -x64"

    def test_valid_pkg_managers(self):
        for t in get_all():
            assert t.pkg_manager in ("apt", "dnf"), f"{t.name} has invalid pkg_manager"

    def test_valid_families(self):
        for t in get_all():
            assert t.family in ("debian", "rhel"), f"{t.name} has invalid family"

    def test_setup_commands_are_lists(self):
        for t in get_all():
            assert isinstance(t.setup_commands, list), f"{t.name} setup_commands not a list"

    def test_python_install_non_empty(self):
        for t in get_all():
            assert t.python_install, f"{t.name} has empty python_install"

    def test_expected_count(self):
        assert len(get_all()) == 7


class TestGetAll:
    def test_returns_all_entries(self):
        assert len(get_all()) == 7

    def test_returns_copy(self):
        a = get_all()
        b = get_all()
        assert a is not b
        a.append("junk")
        assert len(get_all()) == 7


class TestGetByName:
    def test_found(self):
        t = get_by_name("ubuntu-24.04")
        assert t.name == "ubuntu-24.04"
        assert t.image == "ubuntu-24-04-x64"

    def test_not_found_raises_key_error(self):
        with pytest.raises(KeyError, match="no-such-os"):
            get_by_name("no-such-os")

    def test_all_names_retrievable(self):
        for t in get_all():
            found = get_by_name(t.name)
            assert found == t


class TestGetByFamily:
    def test_debian_returns_3(self):
        assert len(get_by_family("debian")) == 3

    def test_rhel_returns_4(self):
        assert len(get_by_family("rhel")) == 4

    def test_unknown_returns_empty(self):
        assert get_by_family("bsd") == []


class TestGetByPkgManager:
    def test_apt_returns_3(self):
        assert len(get_by_pkg_manager("apt")) == 3

    def test_dnf_returns_4(self):
        assert len(get_by_pkg_manager("dnf")) == 4

    def test_unknown_returns_empty(self):
        assert get_by_pkg_manager("pacman") == []
