import os
import sys
import time
import logging
import json
from playwright.sync_api import sync_playwright

from stream_selector import select_best_stream
from core_processor import CoreProcessor

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AutoStudy")

def get_chrome_user_data_dir():
    """获取 Windows Chrome 用户数据目录"""
    local_app_data = os.getenv('LOCALAPPDATA')
    if local_app_data:
        return os.path.join(local_app_data, r'Google\Chrome\User Data')
    return None

def process_single_url(page_url, context, processor):
    """
    处理单个课程链接：打开 -> 拦截API/视频流 -> 下载 -> 笔记
    """
    logger.info(f"正在处理: {page_url}")
    
    page = context.new_page()
    
    # 存储结果容器
    found_streams = {
        'api_source': None,   # 来自 API 的精准源
        'captured': set()     # 抓包捕获的候选源
    }
    
    # 1. API 拦截处理 (最准确)
    def handle_response(response):
        try:
            # 监听点播和直播的视频信息接口
            if 'getVodVideoInfos' in response.url or 'getLiveVideoInfos' in response.url:
                if response.status == 200:
                    data = response.json()
                    # 解析 body -> videoPlayResponseVoList
                    if 'body' in data and 'videoPlayResponseVoList' in data['body']:
                        video_list = data['body']['videoPlayResponseVoList']
                        if video_list and len(video_list) > 0:
                            # Canvas 规律：Index 0 通常是教师/主画面
                            target_url = video_list[0].get('rtmpUrlHdv') or video_list[0].get('rtmpUrl')
                            if target_url:
                                logger.info(f"🎯 成功拦截 API 元数据，锁定主画面: {target_url}")
                                found_streams['api_source'] = target_url
        except Exception:
            pass # 忽略非 JSON 或解析错误

    # 2. 备用：普通抓包
    def handle_request(request):
        url = request.url
        if ('.mp4' in url or '.m3u8' in url) and len(url) > 20 and not url.startswith('blob:'):
            found_streams['captured'].add(url)

    page.on("response", handle_response)
    page.on("request", handle_request)

    try:
        page.goto(page_url)
        
        # 等待加载。如果 API 拦截成功，可以提前结束等待
        for _ in range(15): # 最多等 15 秒
            if found_streams['api_source']:
                break
            time.sleep(1)
            
        # 如果还没找到 API 数据，可能不是 Canvas 页面，尝试等待视频加载
        if not found_streams['api_source']:
            logger.info("未检测到 Canvas API，等待视频流加载...")
            time.sleep(10) # 给足够时间让视频缓冲，触发 request 抓包

        # 决策：优先使用 API 源，否则从抓包列表中筛选
        final_url = None
        if found_streams['api_source']:
            final_url = found_streams['api_source']
            logger.info("使用 API 锁定的精准源。")
        elif found_streams['captured']:
            logger.info(f"API 拦截失败，从 {len(found_streams['captured'])} 个捕获流中进行智能筛选...")
            # 使用我们优化过的音频检测逻辑
            final_url = select_best_stream(list(found_streams['captured']))
        else:
            logger.error("❌ 未找到任何有效视频流。")
            page.close()
            return False

        # 获取标题
        page_title = page.title()
        
        # 关闭页面释放资源 (视频流 URL 已经拿到了)
        page.close()

        # 执行核心流程
        logger.info(f"开始处理视频流: {final_url}")
        
        # 简单的标题解析
        course_name = "SJTU_Course"
        lesson_title = page_title.strip()
        if '-' in page_title:
            parts = page_title.split('-')
            course_name = parts[0].strip()
            lesson_title = parts[-1].strip()

        result = processor.run_full_workflow(
            url=final_url,
            course_name=course_name,
            lesson_title=lesson_title
        )
        if isinstance(result, dict):
            success = result.get("success", False)
            note_path = result.get("note_path")
            subtitle_path = result.get("subtitle_path")
            if success:
                if note_path:
                    logger.info(f"笔记已保存至: {note_path}")
                if subtitle_path:
                    logger.info(f"字幕已保存至: {subtitle_path}")
        else:
            success = bool(result)
        return success

    except Exception as e:
        logger.error(f"处理页面出错: {e}")
        try:
            page.close()
        except:
            pass
        return False

def main():
    print("=================================================")
    print("   SJTU Canvas 课程全自动助手 (批量版)   ")
    print("   功能：自动拦截主画面 -> 下载 -> 笔记 -> 归档")
    print("=================================================")
    print("请粘贴课程链接 (支持 Canvas 点播/直播页)。")
    print("每行一个链接。输入空行并回车开始执行。")
    
    urls = []
    while True:
        line = input("> ").strip()
        if not line:
            break
        # 简单校验
        if line.startswith("http"):
            urls.append(line)
    
    if not urls:
        print("未输入任何链接，程序退出。")
        return

    print(f"\n已收集 {len(urls)} 个任务，准备开始处理...\n")
    
    # 初始化 Playwright 和 Processor
    user_data_dir = get_chrome_user_data_dir()
    processor = CoreProcessor()
    
    p = sync_playwright().start()
    
    # 尝试复用 Chrome 登录状态
    launch_args = {
        "headless": False,
        "args": ["--start-maximized", "--disable-blink-features=AutomationControlled"]
    }
    
    context = None
    try:
        if user_data_dir and os.path.exists(user_data_dir):
            logger.info(f"加载 Chrome 用户配置: {user_data_dir}")
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir,
                    channel="chrome",
                    **launch_args
                )
            except Exception as e:
                logger.warning(f"复用 Chrome 失败 (请确保已关闭所有 Chrome 窗口): {e}")
                logger.warning("切换到临时浏览器模式 (可能需要您手动登录)...")
                browser = p.chromium.launch(channel="chrome", **launch_args)
                context = browser.new_context()
        else:
            browser = p.chromium.launch(channel="chrome", **launch_args)
            context = browser.new_context()
            
        # 依次处理每个 URL
        for i, url in enumerate(urls):
            logger.info(f"--- 正在执行任务 {i+1}/{len(urls)} ---")
            process_single_url(url, context, processor)
            logger.info(f"--- 任务 {i+1} 结束 ---\n")
            
        logger.info("所有任务处理完毕！")
        input("按回车键退出...")

    except Exception as e:
        logger.error(f"全局异常: {e}")
    finally:
        if context:
            context.close()
        p.stop()

if __name__ == "__main__":
    main()
