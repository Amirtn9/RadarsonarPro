import math

class ScoreEngine:
    """
    موتور مرکزی برای محاسبه امتیازات، میانگین‌گیری و تولید نوارهای وضعیت.
    """

    @staticmethod
    def calculate_server_quality(cpu, ram, disk=0):
        """
        محاسبه امتیاز کیفیت سرور (0 تا 100)
        فرمول: بر اساس میانگین مصرف CPU و RAM
        """
        try:
            # میانگین بار سیستم
            avg_load = (float(cpu) + float(ram)) / 2
            
            # امتیاز معکوس بار است (بار کمتر = امتیاز بیشتر)
            score = max(0, 100 - int(avg_load))
            
            # تعیین آیکون و وضعیت
            if score >= 80:
                status = "💎 عالی"
                color = "🟢"
            elif score >= 50:
                status = "⚖️ خوب"
                color = "🟡"
            else:
                status = "⚠️ تحت فشار"
                color = "🔴"
                
            return {
                'score': score,
                'status_text': status,
                'color': color,
                'avg_load': avg_load
            }
        except:
            return {'score': 0, 'status_text': 'نامشخص', 'color': '⚪️', 'avg_load': 0}

    @staticmethod
    def calculate_config_score(ping, jitter, download_speed=0, upload_speed=0):
        """
        محاسبه امتیاز کانفیگ (0 تا 10)
        فرمول: بر اساس پینگ، جیتر و سرعت (اگر موجود باشد)
        """
        score = 10.0
        
        # جریمه پینگ بالا
        if ping > 1000: score -= 5
        elif ping > 500: score -= 3
        elif ping > 300: score -= 1
        
        # جریمه جیتر بالا (نوسان)
        if jitter > 200: score -= 2
        elif jitter > 50: score -= 1
        
        # جریمه سرعت پایین (اگر تست سرعت انجام شده باشد)
        if download_speed > 0:
            if download_speed < 0.5: score -= 3
            elif download_speed < 2.0: score -= 1
            
        final_score = round(max(0.0, min(10.0, score)), 1)
        
        if final_score >= 8: icon = "💎"
        elif final_score >= 5: icon = "⚖️"
        else: icon = "⚠️"
        
        return final_score, icon

    @staticmethod
    def make_bar(percentage, length=10):
        """
        ساخت نوار وضعیت گرافیکی (Progress Bar)
        """
        if not isinstance(percentage, (int, float)):
            percentage = 0
        blocks = "▏▎▍▌▋▊▉█"
        
        if percentage < 0: percentage = 0
        if percentage > 100: percentage = 100
        
        full_blocks = int((percentage / 100) * length)
        remainder = (percentage / 100) * length - full_blocks
        idx = int(remainder * len(blocks))

        if idx >= len(blocks): idx = len(blocks) - 1

        bar = "█" * full_blocks
        if full_blocks < length:
            bar += blocks[idx] + " " * (length - full_blocks - 1)
            
        return bar

    @staticmethod
    def get_ping_status(ping):
        """تعیین وضعیت پینگ"""
        if ping == 0: return "🔴 Timeout"
        if ping < 200: return f"🟢 {ping}ms"
        if ping < 500: return f"🟡 {ping}ms"
        return f"🔴 {ping}ms"