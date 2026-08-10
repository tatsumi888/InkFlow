import json
import zipfile

import pytest

from inkflow import cli
from inkflow.models import Project

from .conftest import make_pdf

TEST_DEVICE = "custom:150x200"


@pytest.fixture
def folder_with_pdfs(tmp_path):
    folder = tmp_path / "2026-08"
    folder.mkdir()
    make_pdf(folder / "01_特集.pdf", page_count=2)
    make_pdf(folder / "02_連載.pdf", page_count=1)
    return folder


# ---- build（フォルダ入力） ---------------------------------------------


def test_build_from_folder(tmp_path, folder_with_pdfs):
    output = tmp_path / "out.epub"
    code = cli.main(
        [
            "build", str(folder_with_pdfs),
            "-o", str(output),
            "--title", "月刊テスト",
            "--issue", "2026年8月号",
            "--device", TEST_DEVICE,
            "--quiet",
        ]
    )
    assert code == 0
    assert output.is_file()
    with zipfile.ZipFile(output) as archive:
        assert archive.read("mimetype") == b"application/epub+zip"


def test_build_default_output_path(tmp_path, folder_with_pdfs):
    code = cli.main(
        ["build", str(folder_with_pdfs), "--title", "誌名", "--issue", "8月号",
         "--device", TEST_DEVICE, "--quiet"]
    )
    assert code == 0
    assert (folder_with_pdfs / "誌名 8月号.epub").is_file()


def test_build_layout_option_changes_page_count(tmp_path, folder_with_pdfs):
    full = tmp_path / "full.epub"
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(full), "--layout", "full",
         "--device", TEST_DEVICE, "--quiet"]
    )
    with zipfile.ZipFile(full) as archive:
        pages = [n for n in archive.namelist() if n.startswith("OEBPS/text/")]
    # 原稿3ページ → 3枚 + 表紙
    assert len(pages) == 4


def test_build_no_overview_option(tmp_path, folder_with_pdfs):
    output = tmp_path / "no-overview.epub"
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(output), "--no-overview",
         "--device", TEST_DEVICE, "--quiet"]
    )
    with zipfile.ZipFile(output) as archive:
        pages = [n for n in archive.namelist() if n.startswith("OEBPS/text/")]
    # 原稿3ページ x 4分割 + 表紙
    assert len(pages) == 13


def test_build_jpeg_format(tmp_path, folder_with_pdfs):
    output = tmp_path / "jpeg.epub"
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(output), "--format", "jpeg",
         "--jpeg-quality", "70", "--device", TEST_DEVICE, "--quiet"]
    )
    with zipfile.ZipFile(output) as archive:
        assert any(n.endswith(".jpg") for n in archive.namelist())


def test_build_rotate_option_is_stored_in_project(tmp_path, folder_with_pdfs):
    output = tmp_path / "rotated.inkflow.json"
    assert cli.main(["init", str(folder_with_pdfs), "-o", str(output), "--rotate", "cw"]) == 0

    project = Project.load(output)
    assert project.defaults.rotate == 90
    assert all(page.rotate == 90 for a in project.articles for page in a.pages)


def test_build_rotate_ccw(tmp_path, folder_with_pdfs):
    output = tmp_path / "ccw.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(output), "--rotate", "ccw"])
    assert Project.load(output).defaults.rotate == 270


def test_build_rotate_changes_output(tmp_path, folder_with_pdfs):
    upright = tmp_path / "upright.epub"
    rotated = tmp_path / "rotated.epub"
    common = ["--layout", "half_v", "--device", TEST_DEVICE, "--quiet"]
    cli.main(["build", str(folder_with_pdfs), "-o", str(upright), *common])
    cli.main(["build", str(folder_with_pdfs), "-o", str(rotated), "--rotate", "cw", *common])

    with zipfile.ZipFile(upright) as a, zipfile.ZipFile(rotated) as b:
        assert a.read("OEBPS/images/p0000.png") != b.read("OEBPS/images/p0000.png")


def test_build_rotate_overrides_project_file(tmp_path, folder_with_pdfs):
    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])
    assert Project.load(project_path).defaults.rotate == 0

    plain = tmp_path / "plain.epub"
    overridden = tmp_path / "overridden.epub"
    cli.main(["build", str(project_path), "-o", str(plain), "--quiet"])
    cli.main(["build", str(project_path), "-o", str(overridden), "--rotate", "cw", "--quiet"])

    with zipfile.ZipFile(plain) as a, zipfile.ZipFile(overridden) as b:
        assert a.read("OEBPS/images/p0000.png") != b.read("OEBPS/images/p0000.png")


def test_build_without_rotate_option_keeps_project_value(tmp_path, folder_with_pdfs):
    """`--rotate` を付けなければ、プロジェクトの設定を上書きしない。"""
    project_path = tmp_path / "book.inkflow.json"
    cli.main(
        ["init", str(folder_with_pdfs), "-o", str(project_path),
         "--device", TEST_DEVICE, "--rotate", "ccw"]
    )
    with_rotation = tmp_path / "kept.epub"
    cli.main(["build", str(project_path), "-o", str(with_rotation), "--quiet"])

    explicit = tmp_path / "explicit.epub"
    cli.main(["build", str(project_path), "-o", str(explicit), "--rotate", "ccw", "--quiet"])

    with zipfile.ZipFile(with_rotation) as a, zipfile.ZipFile(explicit) as b:
        assert a.read("OEBPS/images/p0000.png") == b.read("OEBPS/images/p0000.png")


def test_rotate_overview_is_stored_in_project(tmp_path, folder_with_pdfs):
    output = tmp_path / "ov.inkflow.json"
    assert cli.main(
        ["init", str(folder_with_pdfs), "-o", str(output),
         "--rotate", "cw", "--rotate-overview", "none"]
    ) == 0

    project = Project.load(output)
    assert project.defaults.rotate == 90
    assert project.defaults.rotate_overview == 0
    assert all(page.rotate_overview == 0 for a in project.articles for page in a.pages)


def test_rotate_overview_same_keeps_none(tmp_path, folder_with_pdfs):
    output = tmp_path / "same.inkflow.json"
    cli.main(
        ["init", str(folder_with_pdfs), "-o", str(output),
         "--rotate", "cw", "--rotate-overview", "same"]
    )
    assert Project.load(output).defaults.rotate_overview is None


def test_rotate_overview_changes_only_the_overview_page(tmp_path, folder_with_pdfs):
    plain = tmp_path / "plain.epub"
    overview_rotated = tmp_path / "ov.epub"
    common = ["--layout", "half_v", "--device", TEST_DEVICE, "--quiet"]
    cli.main(["build", str(folder_with_pdfs), "-o", str(plain), *common])
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(overview_rotated),
         "--rotate-overview", "cw", *common]
    )

    with zipfile.ZipFile(plain) as a, zipfile.ZipFile(overview_rotated) as b:
        # p0000 は俯瞰、p0001 は最初の分割コマ
        assert a.read("OEBPS/images/p0000.png") != b.read("OEBPS/images/p0000.png")


def test_rotate_overview_overrides_project_file(tmp_path, folder_with_pdfs):
    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])
    assert Project.load(project_path).defaults.rotate_overview is None

    plain = tmp_path / "a.epub"
    overridden = tmp_path / "b.epub"
    cli.main(["build", str(project_path), "-o", str(plain), "--quiet"])
    cli.main(
        ["build", str(project_path), "-o", str(overridden),
         "--rotate-overview", "cw", "--quiet"]
    )
    with zipfile.ZipFile(plain) as a, zipfile.ZipFile(overridden) as b:
        assert a.read("OEBPS/images/p0000.png") != b.read("OEBPS/images/p0000.png")


def test_build_gray_levels_reduces_size(tmp_path, folder_with_pdfs):
    """階調数を落とすとファイルが小さくなる（メール添付の上限対策）。"""
    default_path = tmp_path / "gray16.epub"
    low_path = tmp_path / "gray4.epub"
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(default_path),
         "--device", TEST_DEVICE, "--quiet"]
    )
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(low_path), "--gray-levels", "4",
         "--device", TEST_DEVICE, "--quiet"]
    )
    assert low_path.stat().st_size < default_path.stat().st_size


def test_build_missing_input(tmp_path):
    assert cli.main(["build", str(tmp_path / "nope"), "--quiet"]) == 1


def test_build_empty_folder(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert cli.main(["build", str(empty), "--quiet"]) == 1


def test_build_verbose_reraises(tmp_path):
    from inkflow.errors import InkFlowError

    with pytest.raises(InkFlowError):
        cli.main(["build", str(tmp_path / "nope"), "--verbose", "--quiet"])


def test_build_prints_progress(tmp_path, folder_with_pdfs, capsys):
    cli.main(
        ["build", str(folder_with_pdfs), "-o", str(tmp_path / "p.epub"),
         "--device", TEST_DEVICE]
    )
    captured = capsys.readouterr()
    assert "100%" in captured.err
    assert "生成しました" in captured.out
    assert "しおり" in captured.out


# ---- init -------------------------------------------------------------


def test_init_creates_project_file(tmp_path, folder_with_pdfs):
    output = tmp_path / "book.inkflow.json"
    assert cli.main(
        ["init", str(folder_with_pdfs), "-o", str(output),
         "--title", "月刊テスト", "--issue", "2026年8月号", "--layout", "half_v"]
    ) == 0

    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["title"] == "月刊テスト"
    assert data["defaults"]["layout"] == "half_v"
    assert len(data["articles"]) == 2


def test_init_default_output_location(folder_with_pdfs):
    assert cli.main(["init", str(folder_with_pdfs)]) == 0
    assert (folder_with_pdfs / "2026-08.inkflow.json").is_file()


def test_init_uses_folder_name_as_title(folder_with_pdfs):
    cli.main(["init", str(folder_with_pdfs)])
    project = Project.load(folder_with_pdfs / "2026-08.inkflow.json")
    assert project.title == "2026-08"


# ---- build（プロジェクト入力） ------------------------------------------


def test_build_from_project_file(tmp_path, folder_with_pdfs):
    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])

    output = tmp_path / "from-project.epub"
    assert cli.main(["build", str(project_path), "-o", str(output), "--quiet"]) == 0
    assert output.is_file()


def test_build_from_project_respects_edited_titles(tmp_path, folder_with_pdfs):
    import xml.etree.ElementTree as ET

    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])

    project = Project.load(project_path)
    project.articles[0].title = "編集した記事名"
    project.save(project_path)

    output = tmp_path / "edited.epub"
    cli.main(["build", str(project_path), "-o", str(output), "--quiet"])
    with zipfile.ZipFile(output) as archive:
        nav = ET.fromstring(archive.read("OEBPS/nav.xhtml"))
    labels = [
        a.text
        for a in nav.findall(".//{http://www.w3.org/1999/xhtml}nav//{http://www.w3.org/1999/xhtml}a")
    ]
    assert labels[0] == "編集した記事名"


def test_build_from_project_layout_override(tmp_path, folder_with_pdfs):
    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])

    output = tmp_path / "override.epub"
    cli.main(["build", str(project_path), "-o", str(output), "--layout", "full", "--quiet"])
    with zipfile.ZipFile(output) as archive:
        pages = [n for n in archive.namelist() if n.startswith("OEBPS/text/")]
    assert len(pages) == 4


def test_build_from_project_reports_missing_source(tmp_path, folder_with_pdfs):
    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])
    (folder_with_pdfs / "01_特集.pdf").unlink()
    assert cli.main(["build", str(project_path), "--quiet"]) == 1


# ---- 一覧系 -----------------------------------------------------------


def test_layouts_command_lists_every_layout(capsys):
    from inkflow import layouts as layouts_module

    assert cli.main(["layouts"]) == 0
    out = capsys.readouterr().out
    for layout in layouts_module.LAYOUTS:
        assert layout.id in out


def test_devices_command_lists_presets(capsys):
    assert cli.main(["devices"]) == 0
    out = capsys.readouterr().out
    assert "paperwhite_11" in out
    assert "custom:WxH" in out


def test_no_command_exits_with_usage_error():
    with pytest.raises(SystemExit):
        cli.main([])


def test_cli_and_gui_paths_produce_identical_pages(tmp_path, folder_with_pdfs):
    """CLI と GUI（BuildWorker）は同じ builder を通るので、中身が一致する。"""
    from inkflow.gui.worker import BuildWorker

    project_path = tmp_path / "book.inkflow.json"
    cli.main(["init", str(folder_with_pdfs), "-o", str(project_path), "--device", TEST_DEVICE])

    from_cli = tmp_path / "cli.epub"
    cli.main(["build", str(project_path), "-o", str(from_cli), "--quiet"])

    from_gui = tmp_path / "gui.epub"
    worker = BuildWorker(Project.load(project_path), from_gui)
    worker.run()  # スレッドを起こさず、同じ処理を直接呼ぶ

    with zipfile.ZipFile(from_cli) as a, zipfile.ZipFile(from_gui) as b:
        images_a = {n: a.read(n) for n in a.namelist() if n.startswith("OEBPS/images/")}
        images_b = {n: b.read(n) for n in b.namelist() if n.startswith("OEBPS/images/")}
        assert images_a.keys() == images_b.keys()
        assert images_a == images_b
        assert a.read("OEBPS/nav.xhtml") == b.read("OEBPS/nav.xhtml")
