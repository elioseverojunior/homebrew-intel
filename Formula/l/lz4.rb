# Generated from Homebrew/homebrew-core@1abdb18fb70f59fea5797571e7fd964d2f67049d by scripts/tap/render.py; do not edit.
# Hand-written changes belong in patches/lz4.patch.
class Lz4 < Formula
  desc "Extremely Fast Compression algorithm"
  homepage "https://lz4.github.io/lz4/"
  url "https://github.com/lz4/lz4/archive/refs/tags/v1.10.0.tar.gz"
  mirror "http://fresh-center.net/linux/misc/lz4-1.10.0.tar.gz"
  mirror "http://fresh-center.net/linux/misc/legacy/lz4-1.10.0.tar.gz"
  sha256 "537512904744b35e232912055ccf8ec66d768639ff3abe5788d90d792ec5f48b"
  license "BSD-2-Clause"
  head "https://github.com/lz4/lz4.git", branch: "dev"

  livecheck do
    url :stable
    strategy :github_latest
  end

  # bottle block: written by brew pr-pull
  bottle do
    root_url "https://github.com/homebrew-intel/homebrew-tap/releases/download/lz4-1.10.0"
    rebuild 3
    sha256 cellar: :any, sequoia: "c2893f1952eaff740c87d2d5c96d59acb0aa6b0985ef277eb2fc97e4ee989ac1"
  end

  depends_on "homebrew-intel/tap/cmake" => :build

  deny_network_access!

  def install
    system "make", "install", "PREFIX=#{prefix}"
    # Prevent dependents from hardcoding Cellar paths.
    inreplace lib/"pkgconfig/liblz4.pc", prefix, opt_prefix

    # We use CMake for package configuration files. These are currently needed to build `tiledb`.
    # The Makefile is used for everything else as official build system and installs multi-threaded CLI.
    ENV["DESTDIR"] = buildpath
    system "cmake", "-S", "build/cmake", "-B", "build",
                    "-DBUILD_SHARED_LIBS=ON",
                    "-DBUILD_STATIC_LIBS=ON", # for LZ4::lz4_static target
                    "-DLZ4_BUILD_CLI=OFF",
                    *std_cmake_args
    system "cmake", "--build", "build" # needed to run `--install` which rewrites build path in .cmake file
    system "cmake", "--install", "build"
    lib.install File.join(buildpath, lib, "cmake")
  end

  test do
    input = "testing compression and decompression"
    compressed = pipe_output(bin/"lz4", input)
    refute_empty compressed
    decompressed = pipe_output("#{bin}/lz4 -d", compressed)
    assert_equal decompressed, input

    # Make sure lz4 executable is built multi-threaded
    assert_match "multithread", shell_output("#{bin}/lz4 -V")
  end
end
