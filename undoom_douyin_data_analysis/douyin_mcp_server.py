#!/usr/bin/env python3
"""
抖音数据分析 MCP 服务器
基于原始的抖音作品分析工具开发的 MCP 服务器版本
提供数据采集、分析和导出功能
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import pandas as pd
from bs4 import BeautifulSoup
from collections import Counter
import jieba
import traceback

try:
    from DrissionPage import ChromiumPage
    from DrissionPage.errors import ElementNotFoundError
    DRISSION_AVAILABLE = True
except ImportError:
    DRISSION_AVAILABLE = False
    logging.warning("DrissionPage not available. Some features may be limited.")

from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.types import (
    Resource,
    Tool,
    TextContent,
    ImageContent,
    EmbeddedResource,
    LoggingLevel
)
import mcp.types as types
import mcp.server.stdio

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("douyin-mcp")

class DouyinMCPServer:
    """抖音数据分析 MCP 服务器"""
    
    def __init__(self):
        self.server = Server("douyin-analyzer")
        self.collected_data = {
            'videos': [],
            'users': []
        }
        self.page = None
        self.is_running = False
        
        # 设置工具
        self._setup_tools()
        
        # 设置资源
        self._setup_resources()
        
        # 设置处理器
        self._setup_handlers()
    
    def _setup_tools(self):
        """设置可用工具"""
        
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """列出所有可用工具"""
            return [
                Tool(
                    name="search_douyin_videos",
                    description="搜索抖音视频数据",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词"
                            },
                            "scroll_count": {
                                "type": "integer",
                                "description": "滚动次数，默认为10",
                                "default": 10
                            },
                            "delay": {
                                "type": "number",
                                "description": "每次滚动的延迟时间（秒），默认为2",
                                "default": 2.0
                            }
                        },
                        "required": ["keyword"]
                    }
                ),
                Tool(
                    name="search_douyin_users",
                    description="搜索抖音用户数据",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词"
                            },
                            "scroll_count": {
                                "type": "integer",
                                "description": "滚动次数，默认为10",
                                "default": 10
                            },
                            "delay": {
                                "type": "number",
                                "description": "每次滚动的延迟时间（秒），默认为2",
                                "default": 2.0
                            }
                        },
                        "required": ["keyword"]
                    }
                ),
                Tool(
                    name="analyze_interaction_data",
                    description="分析视频互动数据（点赞、评论等）",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="analyze_content_length",
                    description="分析视频标题长度分布",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="analyze_keywords",
                    description="分析视频标题中的高频词汇",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "top_n": {
                                "type": "integer",
                                "description": "返回前N个高频词汇，默认为50",
                                "default": 50
                            }
                        },
                        "required": []
                    }
                ),
                Tool(
                    name="export_data",
                    description="导出采集的数据",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "format": {
                                "type": "string",
                                "enum": ["json", "excel", "csv"],
                                "description": "导出格式",
                                "default": "json"
                            },
                            "data_type": {
                                "type": "string",
                                "enum": ["videos", "users", "all"],
                                "description": "导出数据类型",
                                "default": "videos"
                            },
                            "filename": {
                                "type": "string",
                                "description": "文件名（不包含扩展名）",
                                "default": "douyin_data"
                            }
                        },
                        "required": []
                    }
                ),
                Tool(
                    name="get_data_summary",
                    description="获取当前采集数据的摘要信息",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                ),
                Tool(
                    name="clear_data",
                    description="清空当前采集的数据",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "data_type": {
                                "type": "string",
                                "enum": ["videos", "users", "all"],
                                "description": "要清空的数据类型",
                                "default": "all"
                            }
                        },
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
            """处理工具调用"""
            try:
                if name == "search_douyin_videos":
                    return await self._search_douyin_videos(**arguments)
                elif name == "search_douyin_users":
                    return await self._search_douyin_users(**arguments)
                elif name == "analyze_interaction_data":
                    return await self._analyze_interaction_data()
                elif name == "analyze_content_length":
                    return await self._analyze_content_length()
                elif name == "analyze_keywords":
                    return await self._analyze_keywords(**arguments)
                elif name == "export_data":
                    return await self._export_data(**arguments)
                elif name == "get_data_summary":
                    return await self._get_data_summary()
                elif name == "clear_data":
                    return await self._clear_data(**arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
            except Exception as e:
                logger.error(f"Tool {name} failed: {e}")
                return [types.TextContent(type="text", text=f"错误: {str(e)}")]
    
    def _setup_resources(self):
        """设置资源"""
        
        @self.server.list_resources()
        async def handle_list_resources() -> list[Resource]:
            """列出可用资源"""
            return [
                Resource(
                    uri="douyin://data/videos",
                    name="视频数据",
                    description="当前采集的视频数据",
                    mimeType="application/json"
                ),
                Resource(
                    uri="douyin://data/users",
                    name="用户数据",
                    description="当前采集的用户数据",
                    mimeType="application/json"
                ),
                Resource(
                    uri="douyin://analysis/summary",
                    name="数据摘要",
                    description="数据采集和分析摘要",
                    mimeType="text/plain"
                )
            ]
        
        @self.server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            """读取资源内容"""
            if uri == "douyin://data/videos":
                return json.dumps(self.collected_data, ensure_ascii=False, indent=2)
            elif uri == "douyin://data/users":
                return json.dumps(self.user_data, ensure_ascii=False, indent=2)
            elif uri == "douyin://analysis/summary":
                return self._generate_summary()
            else:
                raise ValueError(f"Unknown resource: {uri}")
    
    def _setup_handlers(self):
        """设置其他处理器"""
        pass
    
    async def _search_douyin_videos(self, keyword: str, scroll_count: int = 10, delay: float = 2.0) -> list[types.TextContent]:
        """搜索抖音视频"""
        if not DRISSION_AVAILABLE:
            return [types.TextContent(type="text", text="错误: DrissionPage 未安装，无法进行数据采集")]
        
        try:
            # 初始化浏览器
            if not await self._init_browser():
                return [types.TextContent(type="text", text="错误: 浏览器初始化失败")]
            
            # 构建搜索URL
            search_url = f"https://www.douyin.com/search/{quote(keyword)}?source=normal_search&type=video"
            logger.info(f"搜索视频: {search_url}")
            
            # 访问页面
            self.page.get(search_url)
            await asyncio.sleep(5)  # 等待页面加载
            
            # 开始滚动采集
            new_data = await self._scroll_and_collect(scroll_count, delay, 'video')
            
            # 添加到已采集数据
            for data in new_data:
                if data not in self.collected_data['videos']:
                    self.collected_data['videos'].append(data)
            
            result_text = f"成功采集到 {len(new_data)} 条视频数据\n"
            result_text += f"当前总共有 {len(self.collected_data['videos'])} 条视频数据\n\n"
            
            # 显示前5条数据作为预览
            if new_data:
                result_text += "最新采集的数据预览:\n"
                for i, data in enumerate(new_data[:5]):
                    result_text += f"{i+1}. {data.get('title', 'N/A')} - {data.get('author', 'N/A')} - {data.get('likes', 'N/A')}赞\n"
            
            return [types.TextContent(type="text", text=result_text)]
            
        except Exception as e:
            logger.error(f"搜索视频失败: {e}")
            return [types.TextContent(type="text", text=f"搜索失败: {str(e)}")]
        finally:
            await self._cleanup_browser()
    
    async def _search_douyin_users(self, keyword: str, scroll_count: int = 10, delay: float = 2.0) -> list[types.TextContent]:
        """搜索抖音用户"""
        if not DRISSION_AVAILABLE:
            return [types.TextContent(type="text", text="错误: DrissionPage 未安装，无法进行数据采集")]
        
        try:
            # 初始化浏览器
            if not await self._init_browser():
                return [types.TextContent(type="text", text="错误: 浏览器初始化失败")]
            
            # 构建搜索URL
            search_url = f"https://www.douyin.com/search/{quote(keyword)}?source=normal_search&type=user"
            logger.info(f"搜索用户: {search_url}")
            
            # 访问页面
            self.page.get(search_url)
            await asyncio.sleep(5)  # 等待页面加载
            
            # 开始滚动采集
            new_data = await self._scroll_and_collect(scroll_count, delay, 'user')
            
            # 添加到已采集数据
            for data in new_data:
                if data not in self.collected_data['users']:
                    self.collected_data['users'].append(data)
            
            result_text = f"成功采集到 {len(new_data)} 条用户数据\n"
            result_text += f"当前总共有 {len(self.collected_data['users'])} 条用户数据\n\n"
            
            # 显示前5条数据作为预览
            if new_data:
                result_text += "最新采集的用户数据预览:\n"
                for i, data in enumerate(new_data[:5]):
                    result_text += f"{i+1}. {data.get('title', 'N/A')} - {data.get('douyin_id', 'N/A')} - {data.get('followers', 'N/A')}粉丝\n"
            
            return [types.TextContent(type="text", text=result_text)]
            
        except Exception as e:
            logger.error(f"搜索用户失败: {e}")
            return [types.TextContent(type="text", text=f"搜索失败: {str(e)}")]
        finally:
            await self._cleanup_browser()
    
    async def _init_browser(self) -> bool:
        """初始化浏览器"""
        try:
            if self.page is None:
                self.page = ChromiumPage()
                await asyncio.sleep(2)  # 等待浏览器启动
            return True
        except Exception as e:
            logger.error(f"浏览器初始化失败: {e}")
            return False
    
    async def _cleanup_browser(self):
        """清理浏览器资源"""
        try:
            if self.page:
                self.page.quit()
                self.page = None
        except Exception as e:
            logger.error(f"清理浏览器失败: {e}")
    
    async def _scroll_and_collect(self, scroll_count: int, delay: float, data_type: str) -> List[Dict]:
        """滚动页面并收集数据"""
        collected = []
        
        try:
            last_height = self.page.run_js("return document.body.scrollHeight")
            
            for i in range(scroll_count):
                # 滚动页面
                self.page.run_js("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(delay)
                
                # 检查是否到达底部
                new_height = self.page.run_js("return document.body.scrollHeight")
                if new_height == last_height:
                    logger.info("已到达页面底部")
                    break
                last_height = new_height
                
                # 获取页面源码并解析
                page_source = self.page.html
                soup = BeautifulSoup(page_source, 'html.parser')
                
                # 根据数据类型选择不同的提取方法
                if data_type == 'user':
                    new_data = self._extract_user_data(soup)
                else:
                    # 直接传递整个soup对象给视频提取方法
                    new_data = self._extract_video_items(soup)
                    logger.info(f"本次滚动提取到 {len(new_data)} 条视频数据")
                
                # 添加新数据（去重）
                for data in new_data:
                    if data not in collected:
                        collected.append(data)
                
                logger.info(f"滚动 {i+1}/{scroll_count}，当前采集 {len(collected)} 条数据")
        
        except Exception as e:
            logger.error(f"滚动采集失败: {e}")
        
        return collected
    
    def _extract_video_items(self, html) -> List[Dict]:
        """提取视频数据"""
        video_data = []
        
        try:
            # 查找视频项目 - 更新为新的页面结构
            video_items = html.select('li.SwZLHMKk')
            logger.info(f"找到 {len(video_items)} 个视频项目")
            
            for item in video_items:
                try:
                    data = self._extract_basic_info(item)
                    self._extract_stats_info(item, data)
                    self._extract_description(item, data)
                    
                    # 清理和格式化数据
                    data = self._clean_and_format_data(data)
                    
                    if data['title']:  # 只添加有标题的数据
                        video_data.append(data)
                        
                except Exception as e:
                    logger.error(f"提取单个视频数据失败: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"提取视频数据失败: {e}")
        
        return video_data
    
    def _extract_basic_info(self, item) -> Dict:
        """提取基本信息"""
        data = {
            'title': '',
            'author': '',
            'video_link': '',
            'publish_time': '',
            'likes': '0',
            'comments': '0',
            'shares': '0'
        }
        
        try:
            # 提取标题 - 新的选择器
            title_elem = item.select_one('div.VDYK8Xd7')
            if title_elem:
                data['title'] = title_elem.get_text(strip=True)
            
            # 提取作者 - 新的选择器
            author_elem = item.select_one('span.MZNczJmS')
            if author_elem:
                data['author'] = author_elem.get_text(strip=True)
            
            # 提取视频链接 - 新的选择器
            link_elem = item.select_one('a.hY8lWHgA')
            if link_elem:
                href = link_elem.get('href', '')
                if href.startswith('//'):
                    data['video_link'] = 'https:' + href
                else:
                    data['video_link'] = href
            
            # 提取发布时间
            time_elem = item.select_one('span.faDtinfi')
            if time_elem:
                data['publish_time'] = time_elem.get_text(strip=True)
        
        except Exception as e:
            logger.error(f"提取基本信息失败: {e}")
        
        return data
    
    def _extract_stats_info(self, item, data: Dict):
        """提取统计信息"""
        try:
            # 查找点赞数 - 新的选择器
            likes_elem = item.select_one('span.cIiU4Muu')
            if likes_elem:
                likes_text = likes_elem.get_text(strip=True)
                data['likes'] = likes_text
            
            # 暂时无法找到评论和分享数的具体选择器，保持默认值
            # 如果需要，可以进一步分析页面结构
        
        except Exception as e:
            logger.error(f"提取统计信息失败: {e}")
    
    def _extract_description(self, item, data: Dict):
        """提取描述信息"""
        try:
            # 尝试从标题元素中获取描述，或者查找其他可能的描述元素
            desc_elem = item.select_one('div.VDYK8Xd7')
            if desc_elem:
                # 如果标题元素包含描述信息，使用它
                data['description'] = desc_elem.get_text(strip=True)
            else:
                # 否则保持为空
                data['description'] = ''
        
        except Exception as e:
            logger.error(f"提取描述信息失败: {e}")
    
    def _clean_and_format_data(self, data: Dict) -> Dict:
        """清理和格式化数据"""
        try:
            # 清理文本
            for key in ['title', 'author', 'description']:
                if key in data:
                    data[key] = self._clean_text(data[key])
            
            # 格式化数字
            for key in ['likes', 'comments', 'shares']:
                if key in data:
                    data[key] = self._format_number(data[key])
            
            # 添加采集时间
            data['collected_at'] = datetime.now().isoformat()
        
        except Exception as e:
            logger.error(f"清理格式化数据失败: {e}")
        
        return data
    
    def _extract_user_data(self, html) -> List[Dict]:
        """提取用户数据"""
        user_data = []
        
        try:
            # 查找用户项目
            user_items = html.select("div.search-result-card > a.hY8lWHgA.poLTDMYS")
            
            for item in user_items:
                try:
                    # 获取用户链接
                    user_link = item.get('href', '')
                    
                    # 获取标题
                    title_elem = item.select_one('div.XQwChAbX p.v9LWb7QE span span span span span')
                    title = title_elem.get_text(strip=True) if title_elem else ''
                    
                    # 获取头像URL
                    avatar_elem = item.select_one('img.RlLOO79h')
                    avatar_url = avatar_elem.get('src', '') if avatar_elem else ''
                    
                    # 获取统计数据
                    stats_div = item.select_one('div.jjebLXt0')
                    douyin_id = ''
                    likes = '0'
                    followers = '0'
                    
                    if stats_div:
                        spans = stats_div.select('span')
                        for span in spans:
                            text = span.get_text(strip=True)
                            
                            if '抖音号:' in text or '抖音号：' in text:
                                id_span = span.select_one('span')
                                if id_span:
                                    douyin_id = id_span.get_text(strip=True)
                            elif '获赞' in text:
                                likes = text.replace('获赞', '').strip()
                            elif '粉丝' in text:
                                followers = text.replace('粉丝', '').strip()
                    
                    # 获取简介
                    desc_elem = item.select_one('p.Kdb5Km3i span span span span span')
                    description = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    # 构建数据
                    data = {
                        'title': title,
                        'douyin_id': douyin_id,
                        'likes': likes,
                        'followers': followers,
                        'description': description,
                        'avatar_url': avatar_url,
                        'user_link': user_link,
                        'collected_at': datetime.now().isoformat()
                    }
                    
                    if data['title']:  # 只添加有标题的数据
                        user_data.append(data)
                        
                except Exception as e:
                    logger.error(f"提取单个用户数据失败: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"提取用户数据失败: {e}")
        
        return user_data
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""
        return text.strip().replace('\n', ' ').replace('\r', ' ')
    
    def _format_number(self, num_str: str) -> str:
        """格式化数字字符串"""
        if not num_str:
            return "0"
        # 移除非数字字符，保留万、千等单位
        import re
        cleaned = re.sub(r'[^0-9万千.]+', '', str(num_str))
        return cleaned if cleaned else "0"
    
    async def _analyze_interaction_data(self) -> list[types.TextContent]:
        """分析互动数据"""
        if not self.collected_data['videos']:
            return [types.TextContent(type="text", text="没有可分析的视频数据")]
        
        try:
            # 将点赞数转换为数字
            likes_data = []
            for data in self.collected_data['videos']:
                likes = str(data.get('likes', '0'))
                try:
                    if '万' in likes:
                        num = float(likes.replace('万', '')) * 10000
                        likes_data.append(int(num))
                    else:
                        likes_data.append(int(likes))
                except (ValueError, TypeError):
                    continue
            
            if not likes_data:
                return [types.TextContent(type="text", text="没有有效的点赞数据可分析")]
            
            # 计算统计数据
            total_likes = sum(likes_data)
            avg_likes = total_likes / len(likes_data)
            max_likes = max(likes_data)
            min_likes = min(likes_data)
            
            # 生成报告
            report = "===== 互动数据分析报告 =====\n\n"
            report += f"总视频数: {len(self.collected_data['videos'])}\n"
            report += f"总点赞数: {self._format_large_number(total_likes)}\n"
            report += f"平均点赞数: {self._format_large_number(int(avg_likes))}\n"
            report += f"最高点赞数: {self._format_large_number(max_likes)}\n"
            report += f"最低点赞数: {self._format_large_number(min_likes)}\n\n"
            
            # 点赞数分布
            ranges = [(0, 100), (101, 1000), (1001, 10000), (10001, 100000), (100001, float('inf'))]
            report += "点赞数分布:\n"
            for start, end in ranges:
                count = sum(1 for likes in likes_data if start <= likes <= end)
                range_text = f"{start}-{end}" if end != float('inf') else f"{start}+"
                percentage = (count / len(likes_data)) * 100
                report += f"{range_text}: {count}个 ({percentage:.1f}%)\n"
            
            return [types.TextContent(type="text", text=report)]
            
        except Exception as e:
            logger.error(f"分析互动数据失败: {e}")
            return [types.TextContent(type="text", text=f"分析失败: {str(e)}")]
    
    async def _analyze_content_length(self) -> list[types.TextContent]:
        """分析内容长度"""
        if not self.collected_data['videos']:
            return [types.TextContent(type="text", text="没有可分析的视频数据")]
        
        try:
            # 计算标题长度
            title_lengths = [len(data.get('title', '')) for data in self.collected_data['videos']]
            title_lengths = [length for length in title_lengths if length > 0]
            
            if not title_lengths:
                return [types.TextContent(type="text", text="没有有效的标题数据可分析")]
            
            # 计算统计数据
            avg_length = sum(title_lengths) / len(title_lengths)
            max_length = max(title_lengths)
            min_length = min(title_lengths)
            
            # 生成报告
            report = "===== 内容长度分析报告 =====\n\n"
            report += f"平均标题长度: {avg_length:.1f}字\n"
            report += f"最长标题: {max_length}字\n"
            report += f"最短标题: {min_length}字\n\n"
            
            # 添加长度分布统计
            length_ranges = [(0, 10), (11, 20), (21, 30), (31, 50), (51, 100), (101, float('inf'))]
            report += "标题长度分布:\n"
            for start, end in length_ranges:
                count = sum(1 for length in title_lengths if start <= length <= end)
                range_text = f"{start}-{end}字" if end != float('inf') else f"{start}字以上"
                percentage = (count / len(title_lengths)) * 100
                report += f"{range_text}: {count}个 ({percentage:.1f}%)\n"
            
            return [types.TextContent(type="text", text=report)]
            
        except Exception as e:
            logger.error(f"分析内容长度失败: {e}")
            return [types.TextContent(type="text", text=f"分析失败: {str(e)}")]
    
    async def _analyze_keywords(self, top_n: int = 50) -> list[types.TextContent]:
        """分析高频词汇"""
        if not self.collected_data['videos']:
            return [types.TextContent(type="text", text="没有可分析的视频数据")]
        
        try:
            # 合并所有标题文本
            all_titles = ' '.join(data.get('title', '') for data in self.collected_data['videos'])
            
            if not all_titles.strip():
                return [types.TextContent(type="text", text="没有有效的标题文本可分析")]
            
            # 设置停用词
            stop_words = {
                '的', '了', '是', '在', '我', '有', '和', '就',
                '都', '而', '及', '与', '着', '或', '等', '为',
                '一个', '没有', '这个', '那个', '但是', '而且',
                '只是', '不过', '这样', '一样', '一直', '一些',
                '这', '那', '也', '你', '我们', '他们', '它们',
                '把', '被', '让', '向', '往', '但', '去', '又',
                '能', '好', '给', '到', '看', '想', '要', '会',
                '多', '能', '这些', '那些', '什么', '怎么', '如何',
                '为什么', '可以', '因为', '所以', '应该', '可能', '应该'
            }
            
            # 使用jieba进行分词
            words = []
            for word in jieba.cut(all_titles):
                if len(word) > 1 and word not in stop_words:
                    words.append(word)
            
            if not words:
                return [types.TextContent(type="text", text="分词后没有有效词汇")]
            
            # 统计词频
            word_counts = Counter(words)
            
            # 生成报告
            report = "===== 高频词汇分析报告 =====\n\n"
            report += f"总标题数: {len(self.collected_data['videos'])}\n"
            report += f"总词汇量: {len(words)}\n"
            report += f"不同词汇数: {len(word_counts)}\n\n"
            
            # 显示高频词汇
            report += f"高频词汇 TOP {top_n}:\n"
            report += "-" * 40 + "\n"
            report += "排名\t词汇\t\t出现次数\t频率\n"
            report += "-" * 40 + "\n"
            
            for rank, (word, count) in enumerate(word_counts.most_common(top_n), 1):
                frequency = (count / len(words)) * 100
                report += f"{rank}\t{word}\t\t{count}\t\t{frequency:.2f}%\n"
            
            return [types.TextContent(type="text", text=report)]
            
        except Exception as e:
            logger.error(f"分析高频词汇失败: {e}")
            return [types.TextContent(type="text", text=f"分析失败: {str(e)}")]
    
    def _format_large_number(self, num: int) -> str:
        """格式化大数字显示"""
        if num >= 10000:
            return f"{num/10000:.1f}万"
        return str(num)
    
    async def _export_data(self, format: str = "json", data_type: str = "videos", filename: str = "douyin_data") -> list[types.TextContent]:
        """导出数据"""
        try:
            # 选择要导出的数据
            if data_type == "users":
                data_to_export = self.collected_data['users']
                if not data_to_export:
                    return [types.TextContent(type="text", text="没有用户数据可导出")]
            elif data_type == "videos":
                data_to_export = self.collected_data['videos']
                if not data_to_export:
                    return [types.TextContent(type="text", text="没有视频数据可导出")]
            elif data_type == "all":
                if not self.collected_data['videos'] and not self.collected_data['users']:
                    return [types.TextContent(type="text", text="没有数据可导出")]
                data_to_export = {
                    "videos": self.collected_data['videos'],
                    "users": self.collected_data['users']
                }
            else:
                return [types.TextContent(type="text", text="无效的数据类型")]
            
            # 生成文件名（使用绝对路径）
            import os as os_module
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_extension = "xlsx" if format == "excel" else format
            base_dir = os_module.path.dirname(os_module.path.abspath(__file__))
            full_filename = os_module.path.join(base_dir, f"{filename}_{timestamp}.{file_extension}")
            
            # 根据格式导出
            if format == "json":
                with open(full_filename, 'w', encoding='utf-8') as f:
                    json.dump(data_to_export, f, ensure_ascii=False, indent=2)
            
            elif format == "excel":
                # 尝试使用可用的Excel引擎
                excel_engine = None
                for engine in ['openpyxl', 'xlsxwriter']:
                    try:
                        # 测试引擎是否可用
                        test_df = pd.DataFrame({'test': [1]})
                        test_filename = f"test_engine_{engine}.xlsx"
                        test_df.to_excel(test_filename, engine=engine, index=False)
                        os_module.remove(test_filename)  # 清理测试文件
                        excel_engine = engine
                        break
                    except Exception:
                        continue
                
                if not excel_engine:
                    return [types.TextContent(type="text", text="错误: 没有可用的Excel引擎，请安装 openpyxl 或 xlsxwriter")]
                
                if data_type == "all":
                    with pd.ExcelWriter(full_filename, engine=excel_engine) as writer:
                        if self.collected_data['videos']:
                            pd.DataFrame(self.collected_data['videos']).to_excel(writer, sheet_name='Videos', index=False)
                        if self.collected_data['users']:
                            pd.DataFrame(self.collected_data['users']).to_excel(writer, sheet_name='Users', index=False)
                else:
                    pd.DataFrame(data_to_export).to_excel(full_filename, index=False, engine=excel_engine)
            
            elif format == "csv":
                if data_type == "all":
                    # CSV格式不支持多表，分别导出
                    if self.collected_data['videos']:
                        video_filename = f"{filename}_videos_{timestamp}.csv"
                        pd.DataFrame(self.collected_data['videos']).to_csv(video_filename, index=False, encoding='utf-8-sig')
                    if self.collected_data['users']:
                        user_filename = f"{filename}_users_{timestamp}.csv"
                        pd.DataFrame(self.collected_data['users']).to_csv(user_filename, index=False, encoding='utf-8-sig')
                    return [types.TextContent(type="text", text=f"数据已导出为CSV格式\n视频数据: {video_filename if self.collected_data['videos'] else '无'}\n用户数据: {user_filename if self.collected_data['users'] else '无'}")]
                else:
                    pd.DataFrame(data_to_export).to_csv(full_filename, index=False, encoding='utf-8-sig')
            
            return [types.TextContent(type="text", text=f"数据已成功导出到: {full_filename}")]
            
        except Exception as e:
            logger.error(f"导出数据失败: {e}")
            logger.error(f"详细错误信息: {traceback.format_exc()}")
            return [types.TextContent(type="text", text=f"导出失败: {str(e)}\n详细错误: {traceback.format_exc()}")]
    
    async def _get_data_summary(self) -> list[types.TextContent]:
        """获取数据摘要"""
        summary = self._generate_summary()
        return [types.TextContent(type="text", text=summary)]
    
    def _generate_summary(self) -> str:
        """生成数据摘要"""
        summary = "===== 抖音数据采集摘要 =====\n\n"
        
        # 视频数据摘要
        summary += f"视频数据: {len(self.collected_data['videos'])} 条\n"
        if self.collected_data['videos']:
            total_likes = 0
            for data in self.collected_data['videos']:
                likes = str(data.get('likes', '0'))
                try:
                    if '万' in likes:
                        num = float(likes.replace('万', '')) * 10000
                        total_likes += int(num)
                    else:
                        total_likes += int(likes)
                except (ValueError, TypeError):
                    continue
            
            summary += f"总点赞数: {self._format_large_number(total_likes)}\n"
            summary += f"平均点赞数: {self._format_large_number(int(total_likes / len(self.collected_data['videos'])) if self.collected_data['videos'] else 0)}\n"
        
        summary += "\n"
        
        # 用户数据摘要
        summary += f"用户数据: {len(self.collected_data['users'])} 条\n"
        if self.collected_data['users']:
            total_followers = 0
            for data in self.collected_data['users']:
                followers = str(data.get('followers', '0'))
                try:
                    if '万' in followers:
                        num = float(followers.replace('万', '')) * 10000
                        total_followers += int(num)
                    else:
                        total_followers += int(followers)
                except (ValueError, TypeError):
                    continue
            
            summary += f"总粉丝数: {self._format_large_number(total_followers)}\n"
            summary += f"平均粉丝数: {self._format_large_number(int(total_followers / len(self.collected_data['users'])) if self.collected_data['users'] else 0)}\n"
        
        summary += "\n"
        summary += f"最后更新时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        
        return summary
    
    async def _clear_data(self, data_type: str = "all") -> list[types.TextContent]:
        """清空数据"""
        try:
            if data_type == "videos":
                count = len(self.collected_data['videos'])
                self.collected_data['videos'].clear()
                return [types.TextContent(type="text", text=f"已清空 {count} 条视频数据")]
            elif data_type == "users":
                count = len(self.collected_data['users'])
                self.collected_data['users'].clear()
                return [types.TextContent(type="text", text=f"已清空 {count} 条用户数据")]
            elif data_type == "all":
                video_count = len(self.collected_data['videos'])
                user_count = len(self.collected_data['users'])
                self.collected_data['videos'].clear()
                self.collected_data['users'].clear()
                return [types.TextContent(type="text", text=f"已清空所有数据\n视频数据: {video_count} 条\n用户数据: {user_count} 条")]
            else:
                return [types.TextContent(type="text", text="无效的数据类型")]
        except Exception as e:
            logger.error(f"清空数据失败: {e}")
            return [types.TextContent(type="text", text=f"清空失败: {str(e)}")]

async def main():
    """主函数"""
    server = DouyinMCPServer()
    
    # 运行服务器
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="douyin-analyzer",
                server_version="1.0.0",
                capabilities=server.server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )

def cli_main():
    """命令行入口点"""
    asyncio.run(main())

if __name__ == "__main__":
    cli_main()