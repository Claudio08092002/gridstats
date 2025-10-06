// app.ts
import { Component, PLATFORM_ID, inject } from '@angular/core';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { CommonModule, isPlatformBrowser } from '@angular/common';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, CommonModule],
  templateUrl: './app.html',
  styleUrls: ['./app.css'],
})
export class App {
  currentYear = new Date().getFullYear();
  showDataNotice = true;
  private platformId = inject(PLATFORM_ID);
  private readonly isBrowser = isPlatformBrowser(this.platformId);

  closeNotice() {
    this.showDataNotice = false;
    // Store in localStorage so it stays closed
    try {
      if (this.isBrowser) {
        window.localStorage.setItem('hideDataNotice', 'true');
      }
    } catch {
      // ignore SSR/unavailable storage
    }
  }

  ngOnInit() {
    // Check if user previously closed the notice
    try {
      if (this.isBrowser) {
        const hideNotice = window.localStorage.getItem('hideDataNotice');
        if (hideNotice === 'true') {
          this.showDataNotice = false;
        }
      }
    } catch {
      // ignore SSR/unavailable storage
    }
  }
}
