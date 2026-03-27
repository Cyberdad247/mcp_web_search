"""
Content distillation helpers integrating Crawl4AI when available.
Converts webpages to token-optimized Markdown for LLM consumption.

This module is best-effort: it will use Crawl4AI's AsyncWebCrawler if available
and gracefully fall back to trafilatura/BeautifulSoup/html2text when not.
"""
from typing import Optional, Any
import asyncio
import logging

from playwright.async_api import BrowserContext, Page

logger = logging.getLogger(__name__)


class ContentDistiller:
    """Distills a webpage into a token-optimized Markdown string.

    Parameters
    - context: a Playwright BrowserContext to reuse (preferred)
    - page: an optional Playwright Page instance (if provided, will be reused)

    Methods
    - distill(url, query=None, basic_view=False) -> dict(title, url, markdown)
    """

    def __init__(self, context: Optional[BrowserContext] = None, page: Optional[Page] = None):
        self.context = context
        self.page = page

    async def _open_page(self, url: str) -> Page:
        if self.page is not None:
            try:
                await self.page.goto(url, wait_until="domcontentloaded")
                return self.page
            except Exception:
                # If reuse failed, ignore and create a fresh page from context
                self.page = None

        if not self.context:
            raise RuntimeError("No BrowserContext or Page available for distillation")

        page = await self.context.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        return page

    async def _crawl_with_crawl4ai(self, page: Page, url: str, query: Optional[str]) -> Optional[str]:
        try:
            # Try to use Crawl4AI if installed. This is best-effort and optional.
            from crawl4ai import AsyncWebCrawler
            from crawl4ai.extractors import JsonCssExtractionStrategy, LLMExtractionStrategy
            from crawl4ai.formatters import FitMarkdown

            logger.info("Using Crawl4AI for extraction")

            # Pre-clean DOM: remove navigation/footer/aside to reduce noise before extraction
            try:
                await page.evaluate("""
                    () => {
                        const selectors = ['nav', 'footer', 'aside'];
                        for (const s of selectors) {
                            document.querySelectorAll(s).forEach(n => n.remove());
                        }
                        // also remove common big header/menus
                        document.querySelectorAll('header, .site-header, .nav, .header').forEach(n => n.remove());
                    }
                """)
            except Exception:
                # non-fatal best-effort DOM cleanup
                pass

            # AsyncWebCrawler usually accepts a Playwright BrowserContext or Page; try both
            crawler = None
            try:
                crawler = AsyncWebCrawler(page=page)
            except Exception:
                try:
                    crawler = AsyncWebCrawler(context=self.context)
                except Exception:
                    crawler = None

            if crawler is None:
                logger.warning("Could not instantiate AsyncWebCrawler with the provided context/page")
                return None

            # Choose a strategy; prefer LLM-based structured extraction when available
            strategy = None
            try:
                strategy = LLMExtractionStrategy()
            except Exception:
                try:
                    strategy = JsonCssExtractionStrategy()
                except Exception:
                    strategy = None

            # If Crawl4AI supports query-based prioritization, try to pass the query into the extractor
            extractor = FitMarkdown(strategy=strategy) if strategy is not None else FitMarkdown()
            try:
                # many extractor implementations accept a `similarity_filter` or `query` param
                if query and hasattr(extractor, "set_similarity_filter"):
                    extractor.set_similarity_filter(query)
                elif query and hasattr(extractor, "similarity_filter"):
                    extractor.similarity_filter = query
            except Exception:
                # best-effort; ignore if not supported
                pass

            # Run the crawler on the single URL and ask for markdown-formatted output
            result = await crawler.crawl(urls=[url], extractor=extractor, query=query)

            # result is expected to be a mapping url->text or similar
            if not result:
                return None

            # Attempt to pick the markdown for our url
            md = None
            if isinstance(result, dict):
                md = result.get(url) or next(iter(result.values()), None)
            else:
                md = str(result)

            md_text = md or ""

            # Query-aware pruning: if a query is provided, fold to paragraphs containing the query
            def _prune_markdown_by_query(md_raw: str, q: Optional[str], context_paragraphs: int = 1) -> str:
                if not q:
                    return md_raw
                ql = q.lower()
                # split into paragraphs (double newlines) and also keep headings
                parts = [p.strip() for p in md_raw.split('\n\n') if p.strip()]
                if not parts:
                    return md_raw

                matched_indices = set()
                for i, p in enumerate(parts):
                    if ql in p.lower():
                        for j in range(max(0, i - context_paragraphs), min(len(parts), i + context_paragraphs + 1)):
                            matched_indices.add(j)

                if not matched_indices:
                    # fallback: if no exact substring matches, try a loose token overlap
                    tokens = set(ql.split())
                    for i, p in enumerate(parts):
                        ptokens = set([t for t in p.lower().split() if len(t) > 2])
                        if tokens & ptokens:
                            for j in range(max(0, i - context_paragraphs), min(len(parts), i + context_paragraphs + 1)):
                                matched_indices.add(j)

                if not matched_indices:
                    return md_raw

                # Reconstruct markdown from selected parts, preserving order
                out_parts = [parts[i] for i in sorted(matched_indices)]
                return '\n\n'.join(out_parts)

            pruned = _prune_markdown_by_query(md_text, query)

            return {"markdown": pruned, "method": "crawl4ai"}
        except Exception as e:
            logger.debug(f"Crawl4AI unavailable or failed: {e}")
            return None

    async def _fallback_extract(self, page: Page) -> str:
        # Fallback extraction: try trafilatura -> html2text -> BeautifulSoup text
        try:
            html = await page.content()
        except Exception:
            html = ""

        # Try trafilatura
        try:
            import trafilatura

            logger.info("Using trafilatura fallback extraction")
            text = trafilatura.extract(html) or ""
            # Minimal markdown cleanup: preserve headings if present
            return {"markdown": text, "method": "trafilatura"}
        except Exception:
            pass

        # Try html2text
        try:
            import html2text

            logger.info("Using html2text fallback extraction")
            h = html2text.HTML2Text()
            h.ignore_links = False
            md = h.handle(html)
            return {"markdown": md, "method": "html2text"}
        except Exception:
            pass

        # Last resort: BeautifulSoup plain text
        try:
            from bs4 import BeautifulSoup

            logger.info("Using BeautifulSoup fallback extraction")
            soup = BeautifulSoup(html, "html.parser")
            # remove typical noisy elements
            for sel in ["header", "footer", "nav", "script", "style", "noscript"]:
                for el in soup.select(sel):
                    el.extract()
            text = soup.get_text(separator="\n\n")
            # collapse multiple blank lines
            lines = [ln.strip() for ln in text.splitlines()]
            out = "\n\n".join([ln for ln in lines if ln])
            return {"markdown": out, "method": "bs4"}
        except Exception:
            return ""

    async def distill(self, url: str, query: Optional[str] = None, basic_view: bool = False) -> dict:
        """Distill the given URL and return a dict with title/url/markdown.

        This function will not raise on missing optional dependencies; instead it will
        return the best-effort markdown string.
        """
        page = None
        created_page = False
        try:
            page = await self._open_page(url)
            created_page = True
        except Exception as e:
            logger.error(f"Failed to open page for distillation: {e}")
            # If we cannot open a page, return an empty markdown payload
            return {"title": "", "url": url, "markdown": ""}

        title = ""
        try:
            title = await page.title()
        except Exception:
            title = ""

        # If the page is a Basic View (gbv=1), avoid using heavy crawlers
        markdown = None
        if not basic_view:
            try:
                markdown = await self._crawl_with_crawl4ai(page, url, query)
            except Exception:
                markdown = None

        if not markdown:
            # fallback to simpler extraction
            markdown = await self._fallback_extract(page)

        # close any page we created (but do not close user-provided page)
        try:
            if created_page and self.page is None:
                await page.close()
        except Exception:
            pass

        # If markdown is already a dict with method, keep it; otherwise wrap
        if isinstance(markdown, dict):
            md_text = markdown.get("markdown", "")
            method = markdown.get("method", "fallback")
        else:
            md_text = markdown or ""
            method = "fallback"

        return {"title": title or "", "url": url, "markdown": md_text, "method": method}
