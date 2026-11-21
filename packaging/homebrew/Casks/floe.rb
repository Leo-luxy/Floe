cask "floe" do
  arch arm: "arm64", intel: "x64"

  version "2.0.0"
  sha256 arm:   "REPLACE_WITH_MACOS_ARM64_DMG_SHA256",
         intel: "REPLACE_WITH_MACOS_X64_DMG_SHA256"

  url "https://github.com/Leo-luxy/Floe/releases/download/v#{version}/Floe-v#{version}-macos-#{arch}.dmg"
  name "Floe"
  desc "Modern cross-platform quantitative stock screening, backtesting, and AI research workbench"
  homepage "https://github.com/Leo-luxy/Floe"

  livecheck do
    url :url
    strategy :github_latest
  end

  depends_on macos: ">= :big_sur"

  app "Floe.app"
  binary "#{appdir}/Floe.app/Contents/MacOS/floe"

  postflight do
    # 开源免付费公证分发：自动移除浏览器/下载产生的隔离扩展属性，使普通用户双击即可直接启动
    system_command "/usr/bin/xattr",
                   args: ["-cr", "#{appdir}/Floe.app"],
                   sudo: false
  end

  zap trash: [
    "~/Library/Application Support/Floe",
    "~/Library/Preferences/io.github.leoluxy.floe.plist",
    "~/Library/Saved Application State/io.github.leoluxy.floe.savedState",
  ]
end
