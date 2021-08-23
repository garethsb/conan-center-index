from conans import ConanFile, tools, AutoToolsBuildEnvironment, MSBuild
from conans.errors import ConanInvalidConfiguration
import os


class MdnsResponderConan(ConanFile):
    name = "mdnsresponder"
    description = "Conan package for Apple's mDNSResponder"
    topics = ("Bonjour", "DNS-SD", "mDNS")
    url = "https://github.com/conan-io/conan-center-index"
    homepage = "https://opensource.apple.com/tarballs/mDNSResponder/"
    license = "Apache-2.0", "BSD-3-Clause"
    settings = "os", "arch", "compiler", "build_type"
    exports_sources = ["patches/**"]

    @property
    def _source_subfolder(self):
        return "source_subfolder"

    def validate(self):
        if self.settings.os not in ["Linux", "Windows"]:
            raise ConanInvalidConfiguration("Only Linux and Windows are supported for this package.")
        if tools.Version(self.version) >= "1096.0.2":
            # recent tarballs (since 1096.0.2) are missing mDNSWindows, so for now, Linux only
            if self.settings.os == "Windows":
                raise ConanInvalidConfiguration("Windows is not supported for version {}.".format(self.version))
            # TCP_NOTSENT_LOWAT is causing build failures for packages built with gcc 4.9
            # the best check would probably be for Linux kernel v3.12, but for now...
            if self.settings.compiler == "gcc" and tools.Version(self.settings.compiler.version) < "5":
                raise ConanInvalidConfiguration("Only gcc 5 or higher is supported for this package.")
            # __has_c_attribute is not available in Clang 5
            if self.settings.compiler == "clang" and tools.Version(self.settings.compiler.version) < "6":
                raise ConanInvalidConfiguration("Only Clang 6 or higher is supported for this package.")

    def source(self):
        tools.get(**self.conan_data["sources"][self.version],
                  destination=self._source_subfolder, strip_root=True)

    @property
    def _posix_folder(self):
        return os.path.join(self._source_subfolder, "mDNSPosix")

    @property
    def _make_build_args(self):
        return [
            "os=linux",
            "-j1",
        ]

    @property
    def _make_build_targets(self):
        return " ".join(["setup", "Daemon", "libdns_sd", "Clients"])

    @property
    def _make_install_args(self):
        return self._make_build_args + [
            "INSTBASE={}".format(self.package_folder),
            "STARTUPSCRIPTDIR={}/bin".format(self.package_folder),
            "RUNLEVELSCRIPTSDIR=",
        ]

    @property
    def _make_install_targets(self):
        # not installing man pages, NSS plugin
        return " ".join(["setup", "InstalledDaemon", "InstalledLib", "InstalledClients"])

    @property
    def _make_env(self):
        return {
            "CFLAGS": "-std=gnu99",
        }

    def _build_make(self):
        with tools.chdir(self._posix_folder):
            autotools = AutoToolsBuildEnvironment(self)
            autotools.make(args=self._make_build_args, target=self._make_build_targets, vars=self._make_env)

    @property
    def _msvc_targets(self):
        return ["mDNSResponder", "DLL", "DLLStub", "dns-sd"]

    @property
    def _msvc_definitions(self):
        return {"_WINSOCK_DEPRECATED_NO_WARNINGS": None}

    @property
    def _msvc_platforms(self):
        return {"x86": "Win32", "x86_64": "x64"}

    @property
    def _msvc_platform(self):
        return self._msvc_platforms[str(self.settings.arch)]

    def _build_msvc(self):
        sln = os.path.join(self._source_subfolder, "mDNSResponder.sln")
        dll_rc = os.path.join(self._source_subfolder, "mDNSWindows", "DLL", "dll.rc")
        dns_sd_rc = os.path.join(self._source_subfolder, "Clients", "DNS-SD.VisualStudio", "dns-sd.rc")
        for rc in [dll_rc, dns_sd_rc]:
            tools.replace_in_file(rc, "afxres.h", "winres.h")
        msbuild = MSBuild(self)
        msbuild.build(sln, targets=self._msvc_targets, platforms=self._msvc_platforms, definitions=self._msvc_definitions)

    def build(self):
        for patch in self.conan_data.get("patches", {}).get(self.version, []):
            tools.patch(**patch)
        if self.settings.os == "Linux":
            self._build_make()
        elif self.settings.os == "Windows":
            self._build_msvc()

    def _install_make(self):
        for dir in ["bin", "include", "lib", "sbin"]:
            tools.mkdir(os.path.join(self.package_folder, dir))
        with tools.chdir(self._posix_folder):
            autotools = AutoToolsBuildEnvironment(self)
            autotools.make(args=self._make_install_args, target=self._make_install_targets, vars=self._make_env)
        # package the daemon in bin too
        tools.rename(os.path.join(self.package_folder, "sbin", "mdnsd"),
                     os.path.join(self.package_folder, "bin", "mdnsd"))
        tools.rmdir(os.path.join(self.package_folder, "sbin"))

    def _msvc_build_folder(self, *argv):
        return os.path.join(self._source_subfolder, *argv, self._msvc_platform, str(self.settings.build_type))

    def _install_msvc(self):
        self.copy("mDNSResponder.exe", dst="bin", src=self._msvc_build_folder("mDNSWindows", "SystemService"))
        self.copy("dns_sd.h", dst="include", src=os.path.join(self._source_subfolder, "mDNSShared"))
        self.copy("dnssd.dll", dst="bin", src=self._msvc_build_folder("mDNSWindows", "DLL"))
        self.copy("dnssdStatic.lib", dst="lib", src=self._msvc_build_folder("mDNSWindows", "DLLStub"))
        # rename consistently with Bonjour SDK
        tools.rename(src=os.path.join(self.package_folder, "lib", "dnssdStatic.lib"),
                     dst=os.path.join(self.package_folder, "lib", "dnssd.lib"))
        self.copy("dns-sd.exe", dst="bin", src=self._msvc_build_folder("Clients", "DNS-SD.VisualStudio"))

    def package(self):
        self.copy("LICENSE", dst="licenses", src=self._source_subfolder)
        if self.settings.os == "Linux":
            self._install_make()
        elif self.settings.os == "Windows":
            self._install_msvc()

    def package_info(self):
        if self.settings.os == "Linux":
            self.cpp_info.libs = ["dns_sd"]
        elif self.settings.os == "Windows":
            self.cpp_info.libs = ["dnssd"]

        # add path for daemon (mdnsd, mDNSResponder) and client (dns-sd)
        bin_path = os.path.join(self.package_folder, "bin")
        self.output.info("Appending PATH environment variable: {}".format(bin_path))
        self.env_info.PATH.append(bin_path)
