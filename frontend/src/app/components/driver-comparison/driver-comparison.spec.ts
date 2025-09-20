import { ComponentFixture, TestBed } from '@angular/core/testing';

import { DriverComparison } from './driver-comparison';

describe('DriverComparison', () => {
  let component: DriverComparison;
  let fixture: ComponentFixture<DriverComparison>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [DriverComparison]
    })
    .compileComponents();

    fixture = TestBed.createComponent(DriverComparison);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
