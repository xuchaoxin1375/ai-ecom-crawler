import { ImageProxyForm } from "./ImageProxyForm";

export function ImageProxySettings() {
  return (
    <section
      id="image-proxy"
      className="scroll-mt-20 rounded-panel border border-line bg-surface"
    >
      <div className="border-b border-line px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">图片加载代理</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
          商品图片由服务端取图，浏览器不再直接访问原图。自动模式依次尝试任务或站点代理、服务默认代理、系统图片代理，最后直连；指定模式只使用下面填写的代理，失败不回退。
        </p>
      </div>
      <div className="px-4 py-4 sm:px-6">
        <ImageProxyForm />
      </div>
    </section>
  );
}
