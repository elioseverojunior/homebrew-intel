# Generated from Homebrew/homebrew-core@1abdb18fb70f59fea5797571e7fd964d2f67049d by scripts/tap/render.py; do not edit.
# Hand-written changes belong in patches/cmake.patch.
class Cmake < Formula
  desc "Cross-platform make"
  homepage "https://www.cmake.org/"
  url "https://github.com/Kitware/CMake/releases/download/v4.4.4/cmake-4.4.4.tar.gz"
  mirror "http://fresh-center.net/linux/misc/cmake-4.4.4.tar.gz"
  mirror "http://fresh-center.net/linux/misc/legacy/cmake-4.4.4.tar.gz"
  sha256 "bd24c30d80a7744ae84b845ff080cc8453b06c622ef01066564108e9cefc44cf"
  license "BSD-3-Clause"
  compatibility_version 1
  head "https://gitlab.kitware.com/cmake/cmake.git", branch: "master"

  # The "latest" release on GitHub has been an unstable version before, and
  # there have been delays between the creation of a tag and the corresponding
  # release, so we check the website's downloads page instead.
  livecheck do
    url "https://cmake.org/download/"
    regex(/href=.*?cmake[._-]v?(\d+(?:\.\d+)+)\.t/i)
  end

  # bottle block: written by brew pr-pull
  bottle do
    root_url "https://github.com/homebrew-intel/homebrew-tap/releases/download/cmake-4.4.4"
    rebuild 2
    sha256 cellar: :any_skip_relocation, sequoia: "45f18d488a9d15d4e8e0fcb23a3bbfb1f2d4fbfc3b1405087801bd0e40dd4c0f"
  end

  uses_from_macos "ncurses"

  on_linux do
    depends_on "openssl@4"
  end

  deny_network_access!

  def install
    args = %W[
      --prefix=#{prefix}
      --no-system-libs
      --parallel=#{ENV.make_jobs}
      --datadir=/share/cmake
      --docdir=/share/doc/cmake
      --mandir=/share/man
    ]
    if OS.mac?
      args += %w[
        --system-zlib
        --system-bzip2
        --system-curl
      ]
    end

    system "./bootstrap", *args, "--", *std_cmake_args,
                                       "-DCMake_INSTALL_BASH_COMP_DIR=#{bash_completion}",
                                       "-DCMake_INSTALL_EMACS_DIR=#{elisp}",
                                       "-DCMake_BUILD_LTO=ON"
    system "make"
    system "make", "install"

    # Move ctest completion because of problems with macOS system bash 3
    (share/"bash-completion/completions").install bash_completion/"ctest"
  end

  def caveats
    <<~EOS
      To install the CMake documentation, run:
        brew install cmake-docs
    EOS
  end

  test do
    (testpath/"CMakeLists.txt").write <<~CMAKE
      cmake_minimum_required(VERSION #{version.major_minor})
      find_package(Ruby)
    CMAKE
    system bin/"cmake", "."

    # These should be supplied in a separate cmake-docs formula.
    refute_path_exists doc/"html"
    refute_path_exists man
  end
end
